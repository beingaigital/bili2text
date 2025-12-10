<p align="center">
  <img src="light_logo2.png" alt="bili2text logo" width="400"/>
</p>


<p align="center">
    <img src="https://img.shields.io/github/stars/lanbinshijie/bili2text" alt="GitHub stars"/>
    <img src="https://img.shields.io/github/license/lanbinshijie/bili2text" alt="GitHub"/>
    <img src="https://img.shields.io/github/last-commit/lanbinshijie/bili2text" alt="GitHub last commit"/>
    <img src="https://img.shields.io/github/v/release/lanbinshijie/bili2text" alt="GitHub release (latest by date)"/>
</p>

# Bili2text 📺

## 转移说明
因为作者的旧账号（lanbinshijie）已经停用，仓库已经转移到新账号（lanbinleo）

感谢各位的支持，如果有任何想法欢迎在issue中提出，或者提交pr~

v2版本开发进度，请查看dev分支；v3版本更名为v2版本

![alt text](./assets/new_v_sc.png)

## 简介 🌟
bili2text 是一个用于将视频（Bilibili、YouTube等）转换为文本的工具🛠️。这个项目通过一个简单的流程实现：下载视频、提取音频、分割音频，并使用 whisper 模型将语音转换为文本。支持AI润色功能，让转写结果更加准确和流畅。整个过程是自动的，只需输入视频链接即可。整个过程行云流水，一步到胃😂

## 功能 🚀
- 🎥**下载视频**：支持从 Bilibili 和 YouTube 下载视频，优先下载 MP4 格式，支持多P视频的下载。
- 🎵**提取音频**：从下载的视频中提取音频。
- 💬**音频分割**：将音频分割成小段，以便于进行高效的语音转文字处理。
- 🤖**语音转文字**：使用 OpenAI 的 whisper 模型将音频转换为文本，生成原始转写文档。
- ✨**AI润色**：使用 Kimi (Moonshot) API 对转写结果进行智能润色，修正错别字、优化断句和表达，生成更精炼的文档。

## 使用方法 📘
1. **克隆仓库**：
   ```bash
   git clone https://github.com/lanbinleo/bili2text.git
   cd bili2text
   ```

2. **安装依赖**：
   安装必要的 Python 库。
   ```bash
   pip install -r requirements.txt
   ```

3. **配置环境变量**（可选，用于AI润色功能）：
   在项目根目录创建 `.env` 文件，配置 Kimi API Key：
   ```bash
   KIMI_API_KEY=your_kimi_api_key_here
   ```
   
   如果不配置，将只能生成原始转写文档，无法使用AI润色功能。

4. **运行脚本**：
   使用 Python 运行 `main.py` 脚本。
   ```python
   python main.py
   ```

   在提示时输入 Bilibili 视频的 av 号。

5. **使用UI界面**：
   ```bash
   python window.py
   ```

   在弹出的窗口中：
   - 输入视频链接（支持 Bilibili 和 YouTube 链接）
   - 点击"加载Whisper"按钮加载模型
   - 点击"提取视频内容"按钮开始处理，生成原始转写文档
   - 如需AI润色，点击"AI修订"按钮，将生成润色后的文档（不会覆盖原始文档）

## 示例 📋
```python
from downBili import download_video
from exAudio import *
from speech2text import *

av = input("请输入av号：")
filename = download_video(av)
foldername = run_split(filename)
run_analysis(foldername, prompt="以下是普通话的句子。这是一个关于{}的视频。".format(filename))
output_path = f"outputs/{foldername}.txt"
print("转换完成！", output_path)
```

## 技术栈 🧰
- [Python](https://www.python.org/) 主要编程语言，负责实现程序逻辑功能
- [Whisper](https://github.com/openai/whisper) 语音转文字模型
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) 视频下载工具，支持 Bilibili、YouTube 等多种平台
- [Kimi (Moonshot)](https://platform.moonshot.cn/) AI润色服务，提供智能文本润色功能
- [Tkiner](https://docs.python.org/3/library/tkinter.html) UI界面展示相关工具
- [TTKbootstrap](https://ttkbootstrap.readthedocs.io/en/latest/zh/) UI界面美化库

## 功能特点 ✨

### 视频下载
- ✅ 支持 Bilibili 视频下载（BV号或完整链接）
- ✅ 支持 YouTube 视频下载
- ✅ 优先下载 MP4 格式，确保兼容性
- ✅ 自动处理多P视频

### 文本转写
- ✅ 使用 Whisper 模型进行高精度语音转文字
- ✅ 支持本地模型和 OpenAI API 云端转写
- ✅ 自动分割长音频，提高处理效率
- ✅ 生成 Markdown 格式的原始转写文档

### AI润色
- ✅ 使用 Kimi (Moonshot) API 进行智能润色
- ✅ 修正错别字、优化断句和表达
- ✅ 保持原意的前提下提升文本质量
- ✅ 润色文档独立保存，不覆盖原始文档

## 后续开发计划 📅

- [X] 生成requirements.txt
- [X] UI化设计
- [X] 支持YouTube视频下载
- [X] 优先下载MP4格式
- [X] AI润色功能


## 运行截图 📷
<!-- assets/screenshot1.png -->
<img src="assets/screenshot3.png" alt="screenshot3" width="600"/>
<img src="assets/screenshot2.png" alt="screenshot2" width="600"/>
<img src="assets/screenshot1.png" alt="screenshot1" width="600"/>

## Star History ⭐

[![Star History Chart](https://api.star-history.com/svg?repos=lanbinshijie/bili2text&type=Date)](https://star-history.com/#lanbinshijie/bili2text&Date)



## 许可证 📄
本项目根据 MIT 许可证发布。

## 贡献 💡
如果你想为这个项目做出贡献，欢迎提交 Pull Request 或创建 Issue。

## 投喂一下！

> TKTg2T7u7xdV4xDAzbzird2qmWoqLanbin

![image](https://github.com/user-attachments/assets/412470b8-7fd5-4632-a085-9c48a9d5e18b)

TRC20链！谢谢大家！

## 致谢 🙏
再此感谢Open Teens对青少年开源社区做出的贡献！[@OpenTeens](https://openteens.org)

## 使用须知 🖥️

**用户在使用 bili2text 工具时，必须遵守用户所在地区的相关版权法律和规定。请确保您有权利下载和转换的视频内容，尊重创作者的劳动成果。**

