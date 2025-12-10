#!/usr/bin/env python3
"""
预先下载 Whisper 模型的脚本
运行此脚本可以预先下载模型，避免在 GUI 中下载时出现 GIL 冲突
"""
import whisper
import sys

def download_model(model_name="small"):
    """下载指定的 Whisper 模型"""
    print(f"正在下载 Whisper 模型: {model_name}")
    print("这可能需要几分钟，请耐心等待...")
    try:
        model = whisper.load_model(model_name)
        print(f"✓ 模型 {model_name} 下载成功！")
        return True
    except Exception as e:
        print(f"✗ 下载失败: {e}")
        return False

if __name__ == "__main__":
    # 默认下载 small 模型，可以通过命令行参数指定
    model = sys.argv[1] if len(sys.argv) > 1 else "small"
    
    print("=" * 50)
    print("Whisper 模型预下载工具")
    print("=" * 50)
    print(f"将下载模型: {model}")
    print("可用模型: tiny, base, small, medium, large")
    print("=" * 50)
    
    if download_model(model):
        print("\n✓ 完成！现在可以在 GUI 中加载模型了。")
    else:
        print("\n✗ 下载失败，请检查网络连接或重试。")


