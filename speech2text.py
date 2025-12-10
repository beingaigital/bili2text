import whisper
import os
import ssl
import certifi
import sys
import requests
import json
from dotenv import load_dotenv
from openai import OpenAI

# 加载.env文件
load_dotenv()

# 修复 SSL 证书验证问题 - 使用 certifi 提供的证书
try:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    ssl._create_default_https_context = lambda: ssl_context
except Exception:
    # 如果 certifi 不可用，临时禁用验证（不推荐，但可以工作）
    ssl._create_default_https_context = ssl._create_unverified_context

# 禁用 tqdm 进度条以避免 GUI 环境中的线程问题
os.environ['TQDM_DISABLE'] = '1'

whisper_model = None
USE_OPENAI_API = bool(os.getenv("OPENAI_API_KEY")) and str(os.getenv("USE_OPENAI_WHISPER", "0")).lower() not in ("0", "false", "no")
OPENAI_MODEL = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")
KIMI_API_KEY = os.getenv("KIMI_API_KEY")
KIMI_API_BASE = os.getenv("KIMI_API_BASE", "https://api.moonshot.cn/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-32k")  # 默认使用 k1 32k 模型，侧重稳健校对

# 停止事件（由外部设置）
stop_event = None

def set_stop_event(event):
    """设置停止事件，用于中断长时间运行的任务"""
    global stop_event
    stop_event = event

# 初始化 Kimi OpenAI 客户端
kimi_client = None
if KIMI_API_KEY:
    try:
        kimi_client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=KIMI_API_BASE,
        )
    except Exception as e:
        print(f"初始化 Kimi 客户端失败: {e}")

def is_cuda_available():
    return whisper.torch.cuda.is_available()

def load_whisper(model="tiny"):
    global whisper_model
    if USE_OPENAI_API:
        print("检测到 OPENAI_API_KEY，启用云端 Whisper 转写，跳过本地模型加载。")
        return
    # 彻底禁用 tqdm 以避免 GUI 环境中的线程问题
    import tqdm
    import tqdm._monitor
    
    # 禁用 tqdm 监控线程
    original_tqdm = tqdm.tqdm
    original_monitor = getattr(tqdm._monitor, 'TMonitor', None)
    
    # 创建一个禁用版本的 tqdm
    def disabled_tqdm(*args, **kwargs):
        kwargs['disable'] = True
        return original_tqdm(*args, **kwargs)
    
    # 替换 tqdm
    tqdm.tqdm = disabled_tqdm
    
    # 尝试禁用监控线程
    try:
        if hasattr(tqdm._monitor, 'TMonitor'):
            class DisabledMonitor:
                def __init__(self, *args, **kwargs):
                    pass
                def start(self):
                    pass
                def stop(self):
                    pass
            tqdm._monitor.TMonitor = DisabledMonitor
    except:
        pass
    
    try:
        whisper_model = whisper.load_model(model, device="cuda" if is_cuda_available() else "cpu")
        print("Whisper模型："+model)
    finally:
        # 恢复原始 tqdm
        tqdm.tqdm = original_tqdm
        if original_monitor:
            tqdm._monitor.TMonitor = original_monitor

def run_analysis(filename, model="tiny", prompt="以下是普通话的句子。"):
    """
    执行语音转文字分析，生成原始转写文档（不进行AI润色）。
    参数:
        filename: 音频文件夹名称
        model: Whisper模型名称（未使用，保留兼容性）
        prompt: 转写提示词
    返回:
        原始转写文本
    """
    global whisper_model
    print("正在加载Whisper模型或准备API...")
    # 读取列表中的音频文件
    audio_list = os.listdir(f"audio/slice/{filename}")
    print("模型准备完成！")
    # 添加排序逻辑
    audio_files = sorted(
        audio_list,
        key=lambda x: int(os.path.splitext(x)[0])  # 按文件名数字排序
    )
    # 创建outputs文件夹
    os.makedirs("outputs", exist_ok=True)
    print("正在转换文本...")

    audio_list.sort(key=lambda x: int(x.split(".")[0])) # 将 audio_list 按照切片序号排序

    texts = []
    for idx, fn in enumerate(audio_files, start=1):
        # 检查是否请求停止
        if stop_event and stop_event.is_set():
            print("任务已停止")
            raise KeyboardInterrupt("用户请求停止任务")
        
        print(f"正在转换第{idx}/{len(audio_files)}个音频... {fn}")
        slice_path = f"audio/slice/{filename}/{fn}"
        if USE_OPENAI_API:
            text = _transcribe_via_openai(slice_path, prompt)
        else:
            result = whisper_model.transcribe(slice_path, initial_prompt=prompt)
            text = "".join([seg["text"] for seg in result.get("segments", []) if seg is not None])
        print(text)
        texts.append(text)

    raw_text = "\n".join(texts)
    
    # 只保存原始转写结果
    output_path = f"outputs/{filename}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# 转写结果（原始）\n\n")
        f.write(raw_text.strip())
        f.write("\n")
    print(f"原始转写结果已保存为 Markdown: {output_path}")
    
    return raw_text


def refine_text(filename, prompt="以下是普通话的句子。"):
    """
    对已生成的原始转写文档进行AI润色，生成新的润色文档。
    参数:
        filename: 音频文件夹名称（用于读取原始文档）
        prompt: 润色提示词
    返回:
        润色后的文本
    """
    if not KIMI_API_KEY:
        raise RuntimeError("未配置 KIMI_API_KEY，无法进行AI润色。请在.env文件中配置。")
    
    if not kimi_client:
        raise RuntimeError("Kimi 客户端未初始化，请检查 KIMI_API_KEY 配置是否正确。")
    
    # 读取原始转写文档
    raw_file_path = f"outputs/{filename}.md"
    if not os.path.exists(raw_file_path):
        raise FileNotFoundError(f"未找到原始转写文档: {raw_file_path}，请先执行转写。")
    
    with open(raw_file_path, "r", encoding="utf-8") as f:
        content = f.read()
        # 提取原始文本（跳过标题）
        lines = content.split("\n")
        raw_text = "\n".join([line for line in lines if not line.startswith("#")]).strip()
    
    try:
        # 检查是否请求停止
        if stop_event and stop_event.is_set():
            print("任务已停止")
            raise KeyboardInterrupt("用户请求停止任务")
        
        print("正在调用 Kimi 进行润色...")
        refined_text = _refine_with_kimi(raw_text, prompt)
        
        # 再次检查是否请求停止
        if stop_event and stop_event.is_set():
            print("任务已停止")
            raise KeyboardInterrupt("用户请求停止任务")
        
        print("润色完成。")
        
        # 保存润色结果到新文件（不覆盖原始文档）
        refined_output_path = f"outputs/{filename}_refined.md"
        with open(refined_output_path, "w", encoding="utf-8") as f:
            f.write("# 转写结果（AI润色版）\n\n")
            f.write(refined_text.strip())
            f.write("\n")
        print(f"AI润色结果已保存为 Markdown: {refined_output_path}")
        
        return refined_text
    except Exception as e:
        print(f"Kimi 润色失败: {e}")
        raise


def _transcribe_via_openai(file_path: str, prompt: str) -> str:
    """使用 OpenAI Whisper API 进行转写，加速 CPU 设备的处理。"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 OPENAI_API_KEY，无法使用云端转写。")
    headers = {"Authorization": f"Bearer {api_key}"}
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, "audio/mpeg")}
        data = {"model": OPENAI_MODEL, "prompt": prompt}
        resp = requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, data=data, files=files, timeout=300)
    if not resp.ok:
        raise RuntimeError(f"OpenAI 转写失败: {resp.status_code} {resp.text}")
    return resp.json().get("text", "")


def _estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量。
    中文大约 1.5 字符 = 1 token，英文大约 4 字符 = 1 token。
    这里使用一个简单的估算：中文字符按 1.5 计算，其他字符按 4 计算。
    """
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    # 中文字符按 1.5 字符/token，其他按 4 字符/token
    estimated_tokens = int(chinese_chars / 1.5 + other_chars / 4)
    return estimated_tokens


def _get_model_max_tokens(model_name: str) -> int:
    """根据模型名称获取最大 token 限制。"""
    model_lower = model_name.lower()
    if "k2" in model_lower or "256k" in model_lower:
        return 256000  # k2 thinking 模型支持 256k
    elif "128k" in model_lower:
        return 128000
    elif "32k" in model_lower:
        return 32000
    elif "8k" in model_lower:
        return 8000
    else:
        # 默认使用 256k（k2 模型）
        return 256000


def _split_text_into_chunks(text: str, max_tokens_per_chunk: int) -> list:
    """
    将文本分割成多个块，每块不超过指定的 token 数量。
    尽量在段落边界（换行符）处分割，保持语义完整性。
    """
    # 估算每块的最大字符数（保守估计，假设全是中文）
    max_chars_per_chunk = int(max_tokens_per_chunk * 1.5)
    
    chunks = []
    paragraphs = text.split('\n')
    current_chunk = []
    current_length = 0
    
    for para in paragraphs:
        para_length = len(para)
        # 如果单个段落就超过限制，需要进一步分割
        if para_length > max_chars_per_chunk:
            # 先保存当前块
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_length = 0
            
            # 将长段落按句子分割
            sentences = para.split('。')
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                sent_length = len(sent)
                if current_length + sent_length + 1 > max_chars_per_chunk:
                    if current_chunk:
                        chunks.append('\n'.join(current_chunk))
                    current_chunk = [sent]
                    current_length = sent_length
                else:
                    current_chunk.append(sent)
                    current_length += sent_length + 1
        else:
            # 检查添加这个段落后是否超过限制
            if current_length + para_length + 1 > max_chars_per_chunk:
                if current_chunk:
                    chunks.append('\n'.join(current_chunk))
                current_chunk = [para]
                current_length = para_length
            else:
                current_chunk.append(para)
                current_length += para_length + 1
    
    # 添加最后一个块
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    return chunks


def _refine_with_kimi(text: str, prompt: str) -> str:
    """调用 Kimi (Moonshot) 进行润色/纠错。支持长文本自动分块处理。"""
    # 获取模型的最大 token 限制
    max_tokens = _get_model_max_tokens(KIMI_MODEL)
    # 估算 prompt 和 system message 的 token（约 200-300 tokens）
    prompt_tokens = _estimate_tokens(prompt) + 300
    # 根据模型大小动态调整每块的最大 token 数（为 prompt 和响应预留空间）
    if max_tokens >= 256000:
        max_text_tokens_per_chunk = 200000  # 256k 模型（k2 thinking）
    elif max_tokens >= 128000:
        max_text_tokens_per_chunk = 100000   # 128k 模型
    elif max_tokens >= 32000:
        max_text_tokens_per_chunk = 25000    # 32k 模型
    else:
        max_text_tokens_per_chunk = 5500     # 8k 模型（保守估计）
    
    # 估算整个文本的 token 数量
    total_tokens = _estimate_tokens(text)
    
    print(f"文档总长度约 {total_tokens} tokens，模型限制 {max_tokens} tokens")
    
    # 对于 k2 模型（256k），大多数文档都可以一次性处理
    if total_tokens + prompt_tokens <= max_tokens:
        if total_tokens <= max_text_tokens_per_chunk:
            print("文档长度在模型限制内，直接处理...")
            return _refine_single_chunk(text, prompt)
    
    # 需要分块处理（对于超长文档）
    print(f"文档较长，将分块处理（每块文本约 {max_text_tokens_per_chunk} tokens）...")
    chunks = _split_text_into_chunks(text, max_text_tokens_per_chunk)
    print(f"共分为 {len(chunks)} 块进行润色")
    
    refined_chunks = []
    for idx, chunk in enumerate(chunks, 1):
        # 检查是否请求停止
        if stop_event and stop_event.is_set():
            print("任务已停止")
            # 将已处理的块和未处理的块合并
            if refined_chunks:
                return '\n\n'.join(refined_chunks) + '\n\n[任务已停止，以下内容未润色]\n\n' + '\n\n'.join(chunks[idx-1:])
            else:
                raise KeyboardInterrupt("用户请求停止任务")
        
        chunk_tokens = _estimate_tokens(chunk)
        print(f"正在润色第 {idx}/{len(chunks)} 块（约 {chunk_tokens} tokens）...")
        try:
            refined_chunk = _refine_single_chunk(chunk, prompt)
            refined_chunks.append(refined_chunk)
        except KeyboardInterrupt:
            raise  # 重新抛出停止请求
        except Exception as e:
            print(f"第 {idx} 块润色失败: {e}，保留原文")
            refined_chunks.append(chunk)  # 失败时保留原文
    
    # 合并所有润色后的块
    print("所有块润色完成，正在合并结果...")
    return '\n\n'.join(refined_chunks)


def _refine_single_chunk(text: str, prompt: str) -> str:
    """对单个文本块调用 Kimi API 进行润色。使用 OpenAI 兼容客户端。"""
    if not kimi_client:
        raise RuntimeError("Kimi 客户端未初始化，请检查 KIMI_API_KEY 配置。")
    
    try:
        # 使用 OpenAI 兼容客户端调用 Kimi API
        response = kimi_client.chat.completions.create(
            model=KIMI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个严格的中文转写润色助手。"
                        "请仅对给定文本进行错别字、标点、断句和轻微语气调整，"
                        "保持原始语序与信息完整，不新增总结、点评、延伸内容，"
                        "不改写成新的风格，也不要删除有效信息。"
                        "如果文本分块提供，也要保持上下文衔接。"
                        "输出与输入同一语种，并保持 Markdown 中的段落结构。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"主题提示：{prompt}\n\n"
                        "以下是转写原文，请仅进行必要的纠错和轻量润色，不要总结：\n"
                        f"{text}"
                    ),
                },
            ],
            temperature=0.15,  # 降低随机性，避免过度创作
            max_tokens=32000,  # 最大输出 tokens（k2 模型支持更大，但这里设置一个合理的上限）
        )
        
        # 获取返回的内容
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content
        else:
            raise RuntimeError("Kimi API 返回空结果")
            
    except Exception as e:
        raise RuntimeError(f"Kimi API 调用失败: {str(e)}")
    
