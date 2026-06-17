# -*- coding: utf-8 -*-
"""
水课快答 - 自动更新程序
检查 GitHub/Gitee 更新并覆盖安装
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# 配置
APP_NAME = "水课快答"
CURRENT_VERSION = "1.3.2"  # 当前版本，需要手动更新
SCRIPT_DIR = Path(__file__).parent.absolute()

# GitHub 配置
GITHUB_OWNER = "GeorgeChou17"
GITHUB_REPO = "ShuiKeKuaiDa"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# Gitee 配置（备用）
GITEE_OWNER = "georgechou17"
GITEE_REPO = "ShuiKeKuaiDa"
GITEE_API = f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}/releases/latest"

# 不覆盖的文件/目录
EXCLUDE_FILES = {
    "update.py",
    ".git",
    ".gitignore",
    "__pycache__",
    ".workbuddy",
    "logs",
    "presets",
    "dist",
    "build",
    "stdout.log",
    "crash.log",
    ".first_run_done",
    ".skip_shortcut_prompt",
    ".env",
}

# 需要保留的用户配置目录
PRESERVE_DIRS = {
    "logs",
    "presets",
}


def get_current_version():
    """获取当前版本号"""
    return CURRENT_VERSION


def parse_version(version_str):
    """解析版本号字符串为元组"""
    try:
        # 移除 'v' 前缀
        if version_str.startswith('v'):
            version_str = version_str[1:]
        # 分割版本号
        parts = version_str.split('.')
        return tuple(int(p) for p in parts)
    except:
        return (0, 0, 0)


def compare_versions(v1, v2):
    """比较两个版本号
    返回: 1 (v1 > v2), -1 (v1 < v2), 0 (相等)
    """
    v1_tuple = parse_version(v1)
    v2_tuple = parse_version(v2)

    if v1_tuple > v2_tuple:
        return 1
    elif v1_tuple < v2_tuple:
        return -1
    return 0


def fetch_json(url, timeout=10):
    """从 URL 获取 JSON 数据"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': f'{APP_NAME}-Updater/{CURRENT_VERSION}'
        })
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"  [WARN] 请求失败 {url}: {e}")
        return None


def check_github_update():
    """检查 GitHub 更新"""
    print("  检查 GitHub 更新...")
    data = fetch_json(GITHUB_API)
    if not data:
        return None

    try:
        tag_name = data.get('tag_name', '')
        release_name = data.get('name', '')
        body = data.get('body', '')
        published_at = data.get('published_at', '')

        # 查找 zip 资产
        zip_url = None
        for asset in data.get('assets', []):
            if asset['name'].endswith('.zip'):
                zip_url = asset['browser_download_url']
                break

        # 如果没有 zip 资产，使用源码 zip
        if not zip_url:
            zip_url = data.get('zipball_url')

        return {
            'source': 'GitHub',
            'version': tag_name,
            'name': release_name,
            'body': body,
            'published_at': published_at,
            'zip_url': zip_url,
        }
    except Exception as e:
        print(f"  [WARN] 解析 GitHub 数据失败: {e}")
        return None


def check_gitee_update():
    """检查 Gitee 更新"""
    print("  检查 Gitee 更新...")
    data = fetch_json(GITEE_API)
    if not data:
        return None

    try:
        tag_name = data.get('tag_name', '')
        release_name = data.get('name', '')
        body = data.get('body', '')
        published_at = data.get('created_at', '')

        # 查找 zip 资产
        zip_url = None
        for asset in data.get('assets', []):
            if asset['name'].endswith('.zip'):
                zip_url = asset['browser_download_url']
                break

        # 如果没有 zip 资产，使用源码 zip
        if not zip_url:
            zip_url = f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/repository/archive/{tag_name}.zip"

        return {
            'source': 'Gitee',
            'version': tag_name,
            'name': release_name,
            'body': body,
            'published_at': published_at,
            'zip_url': zip_url,
        }
    except Exception as e:
        print(f"  [WARN] 解析 Gitee 数据失败: {e}")
        return None


def check_for_updates():
    """检查更新（优先 Gitee，备用 GitHub）"""
    print("\n  正在检查更新...")

    # 先检查 Gitee（国内访问更快）
    release = check_gitee_update()
    if release and release.get('zip_url'):
        return release

    # 备用：检查 GitHub
    print("  [INFO] Gitee 不可用，尝试 GitHub...")
    release = check_github_update()
    if release and release.get('zip_url'):
        return release

    return None


def download_file(url, dest_path, progress_callback=None):
    """下载文件（支持暂停/继续/停止）"""
    import threading
    import msvcrt  # Windows 专用

    # 下载状态
    state = {
        'paused': False,
        'stopped': False,
        'downloaded': 0,
        'total_size': 0
    }

    def keyboard_listener():
        """监听键盘输入"""
        while not state['stopped']:
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
                if key == 'p':
                    state['paused'] = not state['paused']
                    if state['paused']:
                        print("\n  [暂停] 按 P 继续，按 S 停止", end='', flush=True)
                    else:
                        print("\n  [继续] 下载中...", end='', flush=True)
                elif key == 's':
                    state['stopped'] = True
                    print("\n  [停止] 正在停止下载...", end='', flush=True)
            import time
            time.sleep(0.1)

    # 启动键盘监听线程
    listener_thread = threading.Thread(target=keyboard_listener, daemon=True)
    listener_thread.start()

    try:
        # 显示操作提示
        print("  操作提示: P=暂停/继续  S=停止")
        print("  ─────────────────────────────────")

        req = urllib.request.Request(url, headers={
            'User-Agent': f'{APP_NAME}-Updater/{CURRENT_VERSION}'
        })
        with urllib.request.urlopen(req, timeout=30) as response:
            total_size = response.headers.get('content-length')
            total_size = int(total_size) if total_size else 0
            state['total_size'] = total_size

            downloaded = 0
            block_size = 8192
            last_percent = -1

            with open(dest_path, 'wb') as f:
                while True:
                    # 检查是否停止
                    if state['stopped']:
                        print(f"\n  下载已停止")
                        return False

                    # 检查是否暂停
                    if state['paused']:
                        import time
                        time.sleep(0.1)
                        continue

                    # 读取数据
                    block = response.read(block_size)
                    if not block:
                        break

                    f.write(block)
                    downloaded += len(block)
                    state['downloaded'] = downloaded

                    # 更新进度
                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        if percent != last_percent:
                            last_percent = percent
                            # 进度条
                            bar_length = 30
                            filled = int(bar_length * downloaded / total_size)
                            bar = '█' * filled + '░' * (bar_length - filled)
                            mb_down = downloaded / 1024 / 1024
                            mb_total = total_size / 1024 / 1024
                            print(f"\r  [{bar}] {percent}% ({mb_down:.1f}/{mb_total:.1f} MB)", end='', flush=True)

        print(f"\n  下载完成!")
        return True

    except Exception as e:
        if not state['stopped']:
            print(f"\n  [ERROR] 下载失败: {e}")
        return False


def extract_zip(zip_path, extract_to):
    """解压 zip 文件"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        return True
    except Exception as e:
        print(f"  [ERROR] 解压失败: {e}")
        return False


def should_exclude(path_name):
    """检查文件/目录是否应该排除"""
    # 检查完整路径名
    for exclude in EXCLUDE_FILES:
        if path_name == exclude or path_name.startswith(exclude + os.sep):
            return True
    return False


def backup_user_data():
    """备份用户数据"""
    backup_dir = SCRIPT_DIR / ".backup_update"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    backup_dir.mkdir(exist_ok=True)

    # 备份用户配置目录
    for dir_name in PRESERVE_DIRS:
        src = SCRIPT_DIR / dir_name
        if src.exists():
            dst = backup_dir / dir_name
            shutil.copytree(src, dst)

    return backup_dir


def restore_user_data(backup_dir):
    """恢复用户数据"""
    if not backup_dir.exists():
        return

    for dir_name in PRESERVE_DIRS:
        src = backup_dir / dir_name
        if src.exists():
            dst = SCRIPT_DIR / dir_name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    # 清理备份
    shutil.rmtree(backup_dir)


def apply_update(release_info):
    """应用更新"""
    version = release_info['version']
    zip_url = release_info['zip_url']
    source = release_info['source']

    print(f"\n  ============================================")
    print(f"  发现新版本: {version}")
    print(f"  来源: {source}")
    print(f"  当前版本: {CURRENT_VERSION}")
    print(f"  ============================================")

    # 显示更新日志
    body = release_info.get('body', '')
    if body:
        print(f"\n  更新日志:")
        print(f"  {'-' * 40}")
        for line in body.split('\n')[:10]:  # 只显示前10行
            print(f"  {line}")
        if len(body.split('\n')) > 10:
            print(f"  ... (更多内容请查看 GitHub)")
        print(f"  {'-' * 40}")

    # 确认更新
    confirm = input("\n  是否继续更新？(y/N): ").strip().lower()
    if confirm != 'y':
        print("  已取消更新")
        return False

    # 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "update.zip"
        extract_path = temp_path / "extracted"

        # 下载
        print(f"\n  正在下载更新...")
        if not download_file(zip_path, zip_path):
            return False

        # 解压
        print(f"  正在解压...")
        extract_path.mkdir(exist_ok=True)
        if not extract_zip(zip_path, extract_path):
            return False

        # 查找解压后的目录（可能是 repo-name-version 格式）
        extracted_items = list(extract_path.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            source_dir = extracted_items[0]
        else:
            source_dir = extract_path

        # 备份用户数据
        print(f"  正在备份用户数据...")
        backup_dir = backup_user_data()

        try:
            # 复制文件（排除不需要更新的文件）
            print(f"  正在安装更新...")
            copied_count = 0

            for item in source_dir.rglob('*'):
                relative_path = item.relative_to(source_dir)
                dest_path = SCRIPT_DIR / relative_path

                # 检查是否排除
                if should_exclude(str(relative_path)):
                    continue

                if item.is_file():
                    # 确保目标目录存在
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_path)
                    copied_count += 1
                elif item.is_dir() and not dest_path.exists():
                    dest_path.mkdir(parents=True, exist_ok=True)

            print(f"  已更新 {copied_count} 个文件")

            # 恢复用户数据
            print(f"  正在恢复用户数据...")
            restore_user_data(backup_dir)

            print(f"\n  ============================================")
            print(f"  更新完成！")
            print(f"  版本: {CURRENT_VERSION} -> {version}")
            print(f"  请重新启动程序")
            print(f"  ============================================")

            return True

        except Exception as e:
            print(f"\n  [ERROR] 安装更新失败: {e}")
            # 尝试恢复
            try:
                restore_user_data(backup_dir)
                print(f"  已恢复到更新前状态")
            except:
                print(f"  [ERROR] 恢复失败，请手动恢复")
            return False


def main():
    """主函数"""
    print(f"\n  ============================================")
    print(f"    {APP_NAME} - 自动更新")
    print(f"  ============================================")
    print(f"  当前版本: {CURRENT_VERSION}")

    # 检查更新
    release = check_for_updates()

    if not release:
        print("\n  [INFO] 无法获取更新信息，请检查网络连接")
        print("  你也可以手动下载：")
        print(f"    GitHub: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases")
        print(f"    Gitee: https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases")
        input("\n  按回车键返回...")
        return

    # 比较版本
    remote_version = release['version']
    if compare_versions(remote_version, CURRENT_VERSION) <= 0:
        print(f"\n  [OK] 当前已是最新版本 ({CURRENT_VERSION})")
        input("\n  按回车键返回...")
        return

    # 应用更新
    success = apply_update(release)

    if success:
        input("\n  按回车键退出更新程序...")
    else:
        input("\n  按回车键返回...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  更新已取消")
    except Exception as e:
        print(f"\n  [ERROR] 更新程序出错: {e}")
        import traceback
        traceback.print_exc()
        input("\n  按回车键退出...")
