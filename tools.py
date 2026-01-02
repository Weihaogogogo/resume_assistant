import os
import json

def list_directory(path: str) -> str:
    """列出目录中的文件和子目录"""
    try:
        items = os.listdir(path)
        return f"目录 {path} 中的内容：\n" + "\n".join(items)
    except Exception as e:
        return f"列出目录失败：{str(e)}"

def read_file(file_path: str) -> str:
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return f"文件 {file_path} 的内容：\n{content}"
    except Exception as e:
        return f"读取文件失败：{str(e)}"

def write_file(file_path: str, content: str) -> str:
    """写入文件内容"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"文件 {file_path} 已成功写入"
    except Exception as e:
        return f"写入文件失败：{str(e)}"

def update_resume(data: dict) -> str:
    """更新resume.json文件"""
    try:
        resume_path = os.path.join(os.getcwd(), 'resume.json')
        with open(resume_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return f"resume.json 已成功更新"
    except Exception as e:
        return f"更新resume.json失败：{str(e)}"

def load_resume() -> dict:
    """加载resume.json文件"""
    try:
        resume_path = os.path.join(os.getcwd(), 'resume.json')
        with open(resume_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        # 确保始终返回字典格式
        return {"error": f"加载resume.json失败：{str(e)}"}
