import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import webbrowser
import re
import sys
import threading
from utils import download_video
from exAudio import convert_flv_to_mp3, split_mp3, process_audio_split

speech_to_text = None  # 模型实例
last_folder_name = None  # 存储最后处理的文件夹名称，用于AI修订
stop_event = threading.Event()  # 用于控制任务停止的事件
current_task_thread = None  # 当前正在执行的任务线程

def is_cuda_available(whisper):
    return whisper.torch.cuda.is_available()

def open_popup(text, title="提示"):

    popup = ttk.Toplevel()
    popup.title(title)
    popup.geometry("300x150")
    popup.update_idletasks()
    x = (popup.winfo_screenwidth() - popup.winfo_reqwidth()) // 2
    y = (popup.winfo_screenheight() - popup.winfo_reqheight()) // 2
    popup.geometry("+%d+%d" % (x, y))
    label = ttk.Label(popup, text=text)
    label.pack(pady=10)
    user_choice = ttk.StringVar()

    def on_confirm():
        user_choice.set("confirmed")
        popup.destroy()
    confirm_button = ttk.Button(popup, text="确定", style="primary.TButton", command=on_confirm)
    confirm_button.pack(side=LEFT, padx=10, pady=10)

    def on_cancel():
        user_choice.set("cancelled")
        popup.destroy()
    cancel_button = ttk.Button(popup, text="取消", style="outline-danger.TButton", command=on_cancel)
    cancel_button.pack(side=RIGHT, padx=10, pady=10)
    popup.wait_window()
    return user_choice.get()

def show_log(text, state="INFO"):

    log_text.config(state="normal")
    log_text.insert(END, f"[LOG][{state}] {text}\n")
    log_text.config(state="disabled")

def on_submit_click():
    global speech_to_text, current_task_thread, stop_event
    if speech_to_text is None:
        print("Whisper未加载！请点击加载Whisper按钮。")
        return
    video_link = video_link_entry.get()
    if not video_link:
        print("视频链接不能为空！")
        return
    if open_popup("是否确定生成？可能耗费时间较长", title="提示") == "cancelled":
        return
    
    # 重置停止事件并启动新任务
    stop_event.clear()
    print(f"视频链接: {video_link}")
    current_task_thread = threading.Thread(target=process_video, args=(video_link,))
    current_task_thread.start()
    # 更新按钮状态
    update_button_states(True)

def process_video(video_link):
    global last_folder_name, stop_event
    try:
        print("=" * 10)
        print("正在下载视频...")
        if stop_event.is_set():
            print("任务已停止")
            return
        file_identifier = download_video(str(video_link))
        if file_identifier is None:
            print("=" * 10)
            print("视频下载失败，无法继续处理。请检查网络连接或视频链接是否正确。")
            return
        if stop_event.is_set():
            print("任务已停止")
            return
        print("=" * 10)
        print("正在分割音频...")
        # 使用音频模块处理
        folder_name = process_audio_split(file_identifier)
        if stop_event.is_set():
            print("任务已停止")
            return
        last_folder_name = folder_name  # 保存文件夹名称，供AI修订使用
        print("=" * 10)
        print("正在转换文本（可能耗时较长）...")
        # 传递停止事件给 speech2text
        if hasattr(speech_to_text, 'set_stop_event'):
            speech_to_text.set_stop_event(stop_event)
        speech_to_text.run_analysis(folder_name, 
            prompt="以下是普通话的句子。这是一个关于{}的视频。".format(file_identifier))
        if stop_event.is_set():
            print("任务已停止")
            return
        output_path = f"outputs/{folder_name}.md"
        print("转换完成！原始文档已保存：", output_path)
        print("提示：如需AI润色，请点击'AI修订'按钮。")
    except KeyboardInterrupt:
        print("=" * 10)
        print("任务已停止")
    except FileNotFoundError as e:
        print("=" * 10)
        print(f"处理失败: {e}")
        print("请确保视频文件已成功下载。")
    except Exception as e:
        if stop_event.is_set():
            print("任务已停止")
        else:
            print("=" * 10)
            print(f"处理过程中发生错误: {e}")
    finally:
        # 任务完成或停止后，更新按钮状态
        update_button_states(False)

def on_generate_again_click():
    print("再次生成...")
    print(open_popup("是否再次生成？"))

def on_clear_log_click():
    # 临时恢复原始 stdout/stderr，避免清空期间的输出被重定向回 log_text
    try:
        sys.stdout = _orig_stdout
        sys.stderr = _orig_stderr
    except NameError:
        # 如果还没初始化原始对象，跳过
        pass
    try:
        log_text.config(state="normal")
        log_text.delete('1.0', END)
        log_text.config(state="disabled")
    finally:
        # 重新启用重定向（如果之前启用了）
        try:
            redirect_system_io()
        except Exception:
            # 避免在清空日志时抛出异常导致界面卡住
            pass

def on_show_result_click():
    print("这里是结果...")

def on_stop_click():
    """停止按钮点击处理"""
    global stop_event
    print("=" * 10)
    print("正在停止任务...")
    stop_event.set()
    print("停止请求已发送，任务将在当前步骤完成后停止。")

def update_button_states(task_running):
    """更新按钮状态"""
    global submit_button, ai_refine_button, stop_button
    try:
        if task_running:
            # 任务运行时，禁用提交和AI修订按钮，启用停止按钮
            submit_button.config(state="disabled")
            ai_refine_button.config(state="disabled")
            stop_button.config(state="normal")
        else:
            # 任务停止后，启用提交和AI修订按钮，禁用停止按钮
            submit_button.config(state="normal")
            ai_refine_button.config(state="normal")
            stop_button.config(state="disabled")
    except:
        pass  # 如果按钮还未创建，忽略错误

def on_ai_refine_click():
    """AI修订按钮点击处理"""
    global speech_to_text, last_folder_name, current_task_thread, stop_event
    if speech_to_text is None:
        print("Whisper未加载！请先加载Whisper模型。")
        return
    if last_folder_name is None:
        print("请先完成视频内容提取，再进行AI修订。")
        return
    if open_popup("是否确定进行AI润色？这将生成一个新的润色文档，不会覆盖原始文档。", title="AI修订确认") == "cancelled":
        return
    
    # 重置停止事件并启动新任务
    stop_event.clear()
    current_task_thread = threading.Thread(target=refine_text_with_ai, args=(last_folder_name,))
    current_task_thread.start()
    # 更新按钮状态
    update_button_states(True)

def refine_text_with_ai(folder_name):
    """在独立线程中执行AI润色"""
    global speech_to_text, stop_event
    try:
        print("=" * 10)
        print("正在使用Kimi进行AI润色（可能耗时较长）...")
        if stop_event.is_set():
            print("任务已停止")
            return
        # 从原始文档中提取file_identifier用于prompt
        # 这里简化处理，使用folder_name
        prompt = "以下是普通话的句子。这是一个关于{}的视频。".format(folder_name)
        # 传递停止事件给 speech2text
        if hasattr(speech_to_text, 'set_stop_event'):
            speech_to_text.set_stop_event(stop_event)
        speech_to_text.refine_text(folder_name, prompt=prompt)
        if stop_event.is_set():
            print("任务已停止")
            return
        refined_output_path = f"outputs/{folder_name}_refined.md"
        print("=" * 10)
        print("AI润色完成！润色文档已保存：", refined_output_path)
    except KeyboardInterrupt:
        print("=" * 10)
        print("任务已停止")
    except FileNotFoundError as e:
        if stop_event.is_set():
            print("任务已停止")
        else:
            print("=" * 10)
            print(f"AI润色失败: {e}")
            print("请确保已先完成原始文档的生成。")
    except RuntimeError as e:
        if stop_event.is_set():
            print("任务已停止")
        else:
            print("=" * 10)
            print(f"AI润色失败: {e}")
            print("请检查.env文件中的KIMI_API_KEY配置是否正确。")
    except Exception as e:
        if stop_event.is_set():
            print("任务已停止")
        else:
            print("=" * 10)
            print(f"AI润色过程中发生错误: {e}")
            import traceback
            print(traceback.format_exc())
    finally:
        # 任务完成或停止后，更新按钮状态
        update_button_states(False)

def on_select_model():
    selected_model = model_var.get()
    print(f"选中的模型: {selected_model}")
    print("请点击加载Whisper按钮加载模型！")

def on_confirm_model_click():
    selected_model = model_var.get()
    print(f"确认的模型: {selected_model}")
    print("请点击加载Whisper按钮加载模型！")

def load_whisper_model():
    global speech_to_text
    print("正在加载Whisper模型，请稍候...")
    # 在独立线程中加载模型，避免 GIL 冲突
    def load_in_thread():
        try:
            import speech2text
            global speech_to_text
            speech_to_text = speech2text
            selected_model = model_var.get()
            speech_to_text.load_whisper(model=selected_model)
            # 检查 CUDA 可用性
            try:
                import whisper
                cuda_available = whisper.torch.cuda.is_available()
                msg = "CUDA加速已启用" if cuda_available else "使用CPU计算"
            except:
                msg = "使用CPU计算"
            print(f"加载Whisper成功！模型: {selected_model}, {msg}")
        except Exception as e:
            print(f"加载Whisper失败: {e}")
            import traceback
            print(traceback.format_exc())
    
    thread = threading.Thread(target=load_in_thread, daemon=True)
    thread.start()

def open_github_link(event=None):
    webbrowser.open_new("https://github.com/lanbinshijie/bili2text")

def redirect_system_io():
    global _orig_stdout, _orig_stderr
    # 仅在首次调用时保存原始 stdout/stderr
    if '_orig_stdout' not in globals():
        _orig_stdout = sys.stdout
        _orig_stderr = sys.stderr

    class StdoutRedirector:
        def __init__(self):
            self._buffer = ""
        def write(self, message, state="INFO"):
            if not message:
                return
            # 跳过进度信息
            if "Speed" in message:
                return
            self._buffer += message
            # 只在遇到换行时写入完整行，避免把片段拆成多行日志
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    try:
                        log_text.config(state="normal")
                        log_text.insert(END, f"[LOG][{state}] {line}\n")
                        log_text.config(state="disabled")
                        log_text.see(END)
                    except Exception:
                        # 如果 UI 还没准备好，回退写到原始 stdout，避免丢失日志或递归
                        try:
                            _orig_stdout.write(line + "\n")
                        except Exception:
                            pass
        def flush(self):
            if self._buffer.strip():
                try:
                    log_text.config(state="normal")
                    log_text.insert(END, f"[LOG][INFO] {self._buffer}\n")
                    log_text.config(state="disabled")
                    log_text.see(END)
                except Exception:
                    try:
                        _orig_stdout.write(self._buffer + "\n")
                    except Exception:
                        pass
            self._buffer = ""

    # 安装重定向器
    sys.stdout = StdoutRedirector()
    sys.stderr = StdoutRedirector()

def main():
    global video_link_entry, log_text, model_var, last_folder_name, submit_button, ai_refine_button, stop_button
    app = ttk.Window("Bili2Text - By Lanbin | www.lanbin.top", themename="litera")
    app.geometry("820x540")
    app.iconbitmap("favicon.ico")
    ttk.Label(app, text="Bilibili To Text", font=("Helvetica", 16)).pack(pady=10)
    
    video_link_frame = ttk.Frame(app)
    video_link_entry = ttk.Entry(video_link_frame)
    video_link_entry.pack(side=LEFT, expand=YES, fill=X)
    load_whisper_button = ttk.Button(video_link_frame, text="加载Whisper", command=load_whisper_model, bootstyle="success-outline")
    load_whisper_button.pack(side=RIGHT, padx=5)
    submit_button = ttk.Button(video_link_frame, text="提取视频内容", command=on_submit_click)
    submit_button.pack(side=RIGHT, padx=5)
    stop_button = ttk.Button(video_link_frame, text="停止", command=on_stop_click, bootstyle="danger-outline", state="disabled")
    stop_button.pack(side=RIGHT, padx=5)
    video_link_frame.pack(fill=X, padx=20)
    
    log_text = ttk.ScrolledText(app, height=10, state="disabled")
    log_text.pack(padx=20, pady=10, fill=BOTH, expand=YES)
    
    controls_frame = ttk.Frame(app)
    controls_frame.pack(fill=X, padx=20)
    generate_button = ttk.Button(controls_frame, text="再次生成", command=on_generate_again_click)
    generate_button.pack(side=LEFT, padx=10, pady=10)
    ai_refine_button = ttk.Button(controls_frame, text="AI修订", command=on_ai_refine_click, bootstyle="info-outline")
    ai_refine_button.pack(side=LEFT, padx=10, pady=10)
    show_result_button = ttk.Button(controls_frame, text="展示结果", command=on_show_result_click, bootstyle="success-outline")
    show_result_button.pack(side=LEFT, padx=10, pady=10)
    
    model_var = ttk.StringVar(value="medium")
    model_combobox = ttk.Combobox(controls_frame, textvariable=model_var, values=["tiny", "small", "medium", "large"])
    model_combobox.pack(side=LEFT, padx=10, pady=10)
    model_combobox.set("small")
    
    confirm_model_button = ttk.Button(controls_frame, text="确认模型", command=on_confirm_model_click, bootstyle="primary-outline")
    confirm_model_button.pack(side=LEFT, padx=10, pady=10)
    
    clear_log_button = ttk.Button(controls_frame, text="清空日志", command=on_clear_log_click, bootstyle=DANGER)
    clear_log_button.pack(side=LEFT, padx=10, pady=10)
    
    footer_frame = ttk.Frame(app)
    footer_frame.pack(side=BOTTOM, fill=X)
    author_label = ttk.Label(footer_frame, text="作者：Lanbin")
    author_label.pack(side=LEFT, padx=10, pady=10)
    version_var = ttk.StringVar(value="2.0.0")
    version_label = ttk.Label(footer_frame, text="版本 " + version_var.get(), foreground="gray")
    version_label.pack(side=LEFT, padx=10, pady=10)
    github_link = ttk.Label(footer_frame, text="开源仓库", cursor="hand2", bootstyle=PRIMARY)
    github_link.pack(side=LEFT, padx=10, pady=10)
    github_link.bind("<Button-1>", open_github_link)
    
    redirect_system_io()
    app.mainloop()

if __name__ == "__main__":
    main()
