#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MyGodotBuild — Godot Web 导出配置校验与构建/导出自动化。

校验项：
- export_presets.cfg 中 Web 预设的 custom_template 路径存在
- encrypt_pck=true 时，encryption_include_filters 非空，且
  .godot/export_credentials.cfg 中对应 preset 的 script_encryption_key 为 64 位十六进制

特性：
- 自动使用所有 CPU 核心并行构建
- 自动加载 Emscripten 环境（配置 EMSDK_PATH）
- 导出前自动清理目标文件夹（可选）

用法：
  直接运行进入交互菜单：  python MyGodotBuild.py
  构建模板：             python MyGodotBuild.py --build-template
  完全重建：             python MyGodotBuild.py --build-template --clean
  导出项目：             python MyGodotBuild.py --export --project-dir <路径>
  导出不清理：           python MyGodotBuild.py --export --project-dir <路径> --no-clean-export
  导出并部署：           python MyGodotBuild.py --export --project-dir <路径> --deploy
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------- 配置（可直接修改） ----------
# 脚本加密密钥，用于构建 Web 模板与导出加密。64 个十六进制字符。
# 安全提示：不要在此处硬编码密钥！请使用以下方式之一：
#   1. 环境变量：export SCRIPT_AES256_ENCRYPTION_KEY="your_key_here"
#   2. 本地配置文件：MyGodotBuild.local.toml (已添加到 .gitignore)
SCRIPT_AES256_ENCRYPTION_KEY = ""

# 交互模式下默认项目目录（留空则每次询问）
DEFAULT_PROJECT_DIR = "D:/GitDir/ShiftFall"

# Emscripten SDK 路径（留空则从 PATH 中查找）
# 例如: "D:/GitDir/emsdk" 或 "C:/emsdk"
EMSDK_PATH = "D:/GitDir/emsdk"

# Git 部署配置（自动推送到远程仓库）
GIT_DEPLOY_REPO = "D:/GitDir/game-shift-fall"  # Git 仓库路径
GIT_DEPLOY_DIST_DIR = "dist"  # 仓库中的部署目录
WEB_BUILD_SOURCE_DIR = "D:/ProjectBuildDir/Web"  # Web 构建输出目录


def _get_cpu_cores() -> int:
    """获取 CPU 核心数，用于并行构建。"""
    cores = os.cpu_count()
    return cores if cores else 1


def read_ini(path: Path) -> dict:
    """读取 INI 风格配置，返回 { section: { key: value } }。"""
    text = path.read_text(encoding="utf-8")
    result = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            section = m.group(1).strip()
            result[section] = {}
            continue
        m = re.match(r"^([^=]+)=(.*)$", line)
        if m and section is not None:
            key = m.group(1).strip()
            value = m.group(2).strip().strip('"')
            result[section][key] = value
    return result


def get_ini(ini: dict, section: str, key: str, default: str = "") -> str:
    return ini.get(section, {}).get(key, default)


def is_valid_encryption_key(key: str) -> bool:
    if not key or not key.strip():
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", key.strip()))


def validate_export_config(project_root: Path) -> bool:
    presets_path = project_root / "export_presets.cfg"
    credentials_path = project_root / ".godot" / "export_credentials.cfg"

    if not presets_path.is_file():
        print(f"错误: 未找到 {presets_path}", file=sys.stderr)
        return False

    presets = read_ini(presets_path)
    web_section = None
    web_options_section = None
    for i in range(100):
        sec = f"preset.{i}"
        if sec not in presets:
            break
        if get_ini(presets, sec, "platform") == "Web":
            web_section = sec
            web_options_section = f"preset.{i}.options"
            break

    if web_section is None:
        print("错误: export_presets.cfg 中未找到 platform=Web 的预设。", file=sys.stderr)
        return False

    encrypt_pck = get_ini(presets, web_section, "encrypt_pck") == "true"
    enc_include = get_ini(presets, web_section, "encryption_include_filters")
    template_release = get_ini(presets, web_options_section, "custom_template/release")
    template_debug = get_ini(presets, web_options_section, "custom_template/debug")
    template_path_str = template_release or template_debug

    all_ok = True

    if template_path_str:
        template_path = Path(template_path_str)
        if not template_path.is_absolute():
            template_path = project_root / template_path
        if template_path.exists():
            print(f"  [OK] Web 模板存在: {template_path}")
        else:
            print(f"  [FAIL] Web 模板不存在: {template_path}", file=sys.stderr)
            all_ok = False
    else:
        print("  [FAIL] custom_template/release 与 debug 均为空", file=sys.stderr)
        all_ok = False

    if encrypt_pck:
        if enc_include:
            print(f"  [OK] 加密包含过滤器: {enc_include}")
        else:
            print("  [FAIL] encrypt_pck=true 但 encryption_include_filters 为空", file=sys.stderr)
            all_ok = False

        if credentials_path.is_file():
            creds = read_ini(credentials_path)
            script_key = get_ini(creds, web_section, "script_encryption_key")
            if script_key:
                if is_valid_encryption_key(script_key):
                    print("  [OK] 脚本加密密钥已配置且格式正确 (64 位十六进制)")
                else:
                    print("  [FAIL] script_encryption_key 格式错误，应为 64 个十六进制字符", file=sys.stderr)
                    all_ok = False
            else:
                print("  [FAIL] export_credentials.cfg 中未配置 script_encryption_key", file=sys.stderr)
                all_ok = False
        else:
            print(f"  [FAIL] 未找到 {credentials_path}", file=sys.stderr)
            all_ok = False
    else:
        print("  [OK] 未启用 encrypt_pck，跳过密钥校验")

    if all_ok:
        print("导出配置校验通过。")
    return all_ok


def _get_encryption_key() -> str:
    """优先使用本文件中的密钥，其次环境变量。"""
    key = (SCRIPT_AES256_ENCRYPTION_KEY or "").strip()
    if not key:
        key = os.environ.get("SCRIPT_AES256_ENCRYPTION_KEY", "").strip()
    return key


def _load_emsdk_env(emsdk_path: Path) -> bool:
    """尝试从指定路径加载 emsdk 环境变量。"""
    if not emsdk_path.is_dir():
        return False
    
    # 在 Windows 上使用 PowerShell 脚本
    if sys.platform == "win32":
        emsdk_env_script = emsdk_path / "emsdk_env.ps1"
        if not emsdk_env_script.is_file():
            emsdk_env_script = emsdk_path / "emsdk_env.bat"
            if not emsdk_env_script.is_file():
                return False
    else:
        emsdk_env_script = emsdk_path / "emsdk_env.sh"
        if not emsdk_env_script.is_file():
            return False
    
    print(f"尝试加载 emsdk 环境: {emsdk_env_script}")
    
    try:
        # 运行 emsdk_env 脚本并捕获环境变量
        if sys.platform == "win32":
            # 在 Windows 上，我们需要运行脚本并捕获环境变量
            ps_script = f"& '{emsdk_env_script}' > $null; Get-ChildItem Env: | ForEach-Object {{ \"$($_.Name)=$($_.Value)\" }}"
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                cwd=emsdk_path,
            )
            if result.returncode == 0:
                # 解析环境变量并更新当前进程
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()
                    if '=' in line:
                        key, _, value = line.partition('=')
                        os.environ[key] = value
                print("✓ emsdk 环境变量已加载")
                return True
        else:
            # Linux/Mac 使用 source 命令
            cmd = f'source "{emsdk_env_script}" && env'
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                executable="/bin/bash",
                cwd=emsdk_path,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if '=' in line:
                        key, _, value = line.partition('=')
                        os.environ[key] = value
                print("✓ emsdk 环境变量已加载")
                return True
    except Exception as e:
        print(f"加载 emsdk 环境失败: {e}", file=sys.stderr)
    
    return False


def _check_emscripten(interactive: bool = True) -> bool:
    """检查 Emscripten 是否安装并可用。"""
    if shutil.which("emcc"):
        return True
    
    # 第一次检测失败，尝试从配置的路径加载 emsdk
    if EMSDK_PATH:
        emsdk_path = Path(EMSDK_PATH)
        if _load_emsdk_env(emsdk_path):
            # 重新检查
            if shutil.which("emcc"):
                return True
    
    # 仍然找不到，显示错误信息
    print("错误: 未找到 Emscripten (emcc)。", file=sys.stderr)
    print("\nWeb 平台构建需要 Emscripten 工具链（推荐版本 4.0.11+）", file=sys.stderr)
    
    # 在交互模式下，询问用户是否手动指定 emsdk 路径
    if interactive:
        print("\n您可以：")
        print("  1. 在脚本开头配置 EMSDK_PATH 变量")
        print("  2. 手动运行 emsdk_env.ps1 后再执行脚本")
        print("  3. 或输入 emsdk 安装路径以尝试加载环境")
        
        try:
            user_path = input("\n请输入 emsdk 路径（留空跳过）: ").strip()
            if user_path:
                user_emsdk_path = Path(user_path)
                if _load_emsdk_env(user_emsdk_path):
                    if shutil.which("emcc"):
                        print("✓ 成功加载 emsdk 环境！")
                        return True
                print("✗ 从指定路径加载失败", file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            print()
    
    print("\n安装步骤：", file=sys.stderr)
    print("  1. 下载 Emscripten SDK: https://emscripten.org/docs/getting_started/downloads.html", file=sys.stderr)
    print("  2. 安装后运行: emsdk install latest", file=sys.stderr)
    print("  3. 激活环境: emsdk activate latest", file=sys.stderr)
    print("  4. 重新启动终端以刷新 PATH 环境变量", file=sys.stderr)
    return False


def _prompt_project_dir(engine_dir: Path) -> Optional[Path]:
    """交互式询问项目目录。"""
    default = DEFAULT_PROJECT_DIR.strip() if DEFAULT_PROJECT_DIR else ""
    if default:
        prompt = f"项目目录 [{default}]: "
    else:
        prompt = "项目目录（含 export_presets.cfg）: "
    raw = input(prompt).strip()
    path_str = raw if raw else default
    if not path_str:
        print("未输入项目目录，已跳过。", file=sys.stderr)
        return None
    p = Path(path_str).resolve()
    if not p.is_dir():
        print(f"错误: 目录不存在: {p}", file=sys.stderr)
        return None
    return p


def _run_validate(project_dir: Path) -> bool:
    print("\n--- 校验导出配置 ---")
    return validate_export_config(project_dir)


def _run_build_template(engine_dir: Path, clean: bool = False, interactive: bool = True) -> bool:
    # 检查 Emscripten 是否可用
    if not _check_emscripten(interactive=interactive):
        return False
    
    key = _get_encryption_key()
    if not key:
        print("警告: 未配置密钥（脚本内 SCRIPT_AES256_ENCRYPTION_KEY 或环境变量），将构建无加密模板。", file=sys.stderr)
    elif not is_valid_encryption_key(key):
        print("错误: 密钥格式错误，应为 64 个十六进制字符。", file=sys.stderr)
        return False
    else:
        print("使用已配置的加密密钥构建模板。")
    
    # 如果需要清理，先执行清理
    if clean:
        print("\n--- 清理构建缓存 ---")
        r = subprocess.run(
            ["scons", "platform=web", "--clean"],
            cwd=engine_dir,
            shell=sys.platform == "win32",
        )
        if r.returncode != 0:
            print("警告: scons 清理失败，继续构建。", file=sys.stderr)
    
    # 获取 CPU 核心数用于并行构建
    cpu_cores = _get_cpu_cores()
    print(f"\n--- 构建 Web 模板（使用 {cpu_cores} 个核心） ---")
    r = subprocess.run(
        ["scons", "platform=web", "target=template_release", f"-j{cpu_cores}"],
        cwd=engine_dir,
        shell=sys.platform == "win32",
        env={**os.environ, "SCRIPT_AES256_ENCRYPTION_KEY": key} if key else os.environ,
    )
    if r.returncode != 0:
        print("错误: scons 构建失败。", file=sys.stderr)
        return False
    print("Web 模板构建完成。")
    return True


def _get_web_export_path(project_dir: Path) -> Optional[Path]:
    """从 export_presets.cfg 中获取 Web 导出路径。"""
    presets_path = project_dir / "export_presets.cfg"
    if not presets_path.is_file():
        return None
    
    presets = read_ini(presets_path)
    for i in range(100):
        sec = f"preset.{i}"
        if sec not in presets:
            break
        if get_ini(presets, sec, "platform") == "Web":
            export_path = get_ini(presets, sec, "export_path")
            if export_path:
                path = Path(export_path)
                if not path.is_absolute():
                    path = project_dir / path
                # 返回目录而不是文件
                return path.parent if path.suffix else path
    return None


def _run_export(engine_dir: Path, project_dir: Path, clean: bool = True, interactive: bool = True) -> bool:
    godot_exe = engine_dir / "bin" / "godot.windows.editor.x86_64.exe"
    if not godot_exe.is_file():
        print(f"错误: 未找到 {godot_exe}", file=sys.stderr)
        return False
    project_file = project_dir / "project.godot"
    if not project_file.is_file():
        print(f"错误: 未找到 {project_file}", file=sys.stderr)
        return False
    
    # 清理导出目录
    if clean:
        export_path = _get_web_export_path(project_dir)
        if export_path and export_path.exists() and export_path.is_dir():
            # 统计目录内容
            try:
                items = list(export_path.iterdir())
                file_count = sum(1 for item in items if item.is_file())
                dir_count = sum(1 for item in items if item.is_dir())
                
                print(f"\n警告: 即将清理导出目录内容")
                print(f"  目录: {export_path}")
                print(f"  包含: {file_count} 个文件, {dir_count} 个子目录")
                if items:
                    print(f"  示例: {', '.join(item.name for item in items[:5])}")
                    if len(items) > 5:
                        print(f"        ...还有 {len(items) - 5} 项")
            except Exception as e:
                print(f"\n警告: 即将清理导出目录: {export_path}")
                print(f"  (无法统计内容: {e})")
            
            # 在交互模式下询问用户确认
            if interactive:
                try:
                    confirm = input("\n是否继续清理并导出？[Y/n]: ").strip().lower()
                    if confirm and confirm not in ['y', 'yes', '是']:
                        print("已取消导出。")
                        return False
                except (EOFError, KeyboardInterrupt):
                    print("\n已取消导出。")
                    return False
            
            # 清理目录内容（保留目录本身）
            print(f"\n正在清理导出目录内容...")
            try:
                deleted_files = 0
                deleted_dirs = 0
                for item in export_path.iterdir():
                    try:
                        if item.is_file():
                            item.unlink()
                            deleted_files += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            deleted_dirs += 1
                    except Exception as e:
                        print(f"  警告: 无法删除 {item.name}: {e}", file=sys.stderr)
                
                print(f"✓ 清理完成: 删除了 {deleted_files} 个文件, {deleted_dirs} 个子目录")
                print(f"  目录已保留: {export_path}")
            except Exception as e:
                print(f"警告: 清理失败: {e}", file=sys.stderr)
                if interactive:
                    try:
                        confirm = input("清理失败，是否继续导出？[Y/n]: ").strip().lower()
                        if confirm and confirm not in ['y', 'yes', '是']:
                            return False
                    except (EOFError, KeyboardInterrupt):
                        print("\n已取消导出。")
                        return False
    
    key = _get_encryption_key()
    env = {**os.environ}
    if key:
        env["GODOT_SCRIPT_ENCRYPTION_KEY"] = key
    print("\n--- 导出 Web ---")
    r = subprocess.run(
        [str(godot_exe), "--headless", "--export-release", "Web", str(project_file)],
        cwd=project_dir,
        env=env,
    )
    if r.returncode != 0:
        print("错误: Godot 导出失败。", file=sys.stderr)
        return False
    print("Web 导出完成。")
    return True


def _deploy_to_git(source_dir: Optional[Path] = None, interactive: bool = True) -> bool:
    """将构建文件部署到 Git 仓库并推送。
    
    Args:
        source_dir: 源文件目录（默认使用配置的 WEB_BUILD_SOURCE_DIR）
        interactive: 是否在交互模式（用于确认操作）
    """
    # 检查配置
    if not GIT_DEPLOY_REPO:
        print("错误: 未配置 GIT_DEPLOY_REPO，请在脚本开头配置。", file=sys.stderr)
        return False
    
    repo_path = Path(GIT_DEPLOY_REPO).resolve()
    if not repo_path.is_dir():
        print(f"错误: Git 仓库目录不存在: {repo_path}", file=sys.stderr)
        return False
    
    # 检查是否是 Git 仓库
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        print(f"错误: {repo_path} 不是一个 Git 仓库", file=sys.stderr)
        return False
    
    # 确定源目录
    if source_dir is None:
        if not WEB_BUILD_SOURCE_DIR:
            print("错误: 未配置 WEB_BUILD_SOURCE_DIR，请在脚本开头配置。", file=sys.stderr)
            return False
        source_dir = Path(WEB_BUILD_SOURCE_DIR).resolve()
    
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"错误: 源目录不存在: {source_dir}", file=sys.stderr)
        return False
    
    # 检查源目录是否有文件
    source_files = list(source_dir.glob("*"))
    if not source_files:
        print(f"错误: 源目录为空: {source_dir}", file=sys.stderr)
        return False
    
    # 目标目录
    dist_dir = repo_path / GIT_DEPLOY_DIST_DIR
    
    print("\n--- 部署到 Git 仓库 ---")
    print(f"  源目录: {source_dir}")
    print(f"  目标仓库: {repo_path}")
    print(f"  部署目录: {dist_dir}")
    print(f"  文件数量: {len(source_files)} 个")
    
    # 在交互模式下确认
    if interactive:
        try:
            confirm = input("\n是否继续部署并推送到远程？[Y/n]: ").strip().lower()
            if confirm and confirm not in ['y', 'yes', '是']:
                print("已取消部署。")
                return False
        except (EOFError, KeyboardInterrupt):
            print("\n已取消部署。")
            return False
    
    # 创建 dist 目录（如果不存在）
    dist_dir.mkdir(parents=True, exist_ok=True)
    
    # 清空 dist 目录
    print("\n正在清空部署目录...")
    try:
        deleted_count = 0
        for item in dist_dir.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                    deleted_count += 1
                elif item.is_dir():
                    shutil.rmtree(item)
                    deleted_count += 1
            except Exception as e:
                print(f"  警告: 无法删除 {item.name}: {e}", file=sys.stderr)
        print(f"✓ 已清空 {deleted_count} 项")
    except Exception as e:
        print(f"错误: 清空目录失败: {e}", file=sys.stderr)
        return False
    
    # 拷贝文件
    print(f"\n正在拷贝文件到 {dist_dir}...")
    try:
        copied_count = 0
        for item in source_dir.iterdir():
            dest = dist_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
                copied_count += 1
            elif item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
                copied_count += 1
        print(f"✓ 已拷贝 {copied_count} 项")
    except Exception as e:
        print(f"错误: 拷贝文件失败: {e}", file=sys.stderr)
        return False
    
    # Git 操作
    print("\n正在提交到 Git...")
    try:
        # git add
        r = subprocess.run(
            ["git", "add", GIT_DEPLOY_DIST_DIR],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"错误: git add 失败: {r.stderr}", file=sys.stderr)
            return False
        
        # 检查是否有变更
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if not r.stdout.strip():
            print("✓ 没有变更需要提交")
            return True
        
        # git commit
        commit_msg = f"[BUILD] 更新游戏构建文件\n\n自动部署来自: {source_dir}"
        r = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"错误: git commit 失败: {r.stderr}", file=sys.stderr)
            return False
        print("✓ 已提交到本地仓库")
        
        # git push
        print("\n正在推送到远程仓库...")
        r = subprocess.run(
            ["git", "push", "origin", "master"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"错误: git push 失败: {r.stderr}", file=sys.stderr)
            print("提示: 文件已在本地提交，您可以稍后手动推送。")
            return False
        print("✓ 已推送到远程仓库")
        
    except Exception as e:
        print(f"错误: Git 操作失败: {e}", file=sys.stderr)
        return False
    
    print("\n部署完成！")
    return True


def run_interactive(engine_dir: Path) -> int:
    """交互式菜单。"""
    engine_dir = engine_dir.resolve()
    if not engine_dir.is_dir():
        print(f"错误: 引擎目录不存在: {engine_dir}", file=sys.stderr)
        return 1

    print("\nMyGodotBuild — Web 构建/导出")
    print(f"引擎目录: {engine_dir}\n")

    while True:
        print("  1) 仅校验项目导出配置")
        print("  2) 构建 Web 模板（加密）")
        print("  3) 导出项目 Web")
        print("  4) 先构建模板，再导出项目")
        print("  5) 完全重新构建 Web 模板（清理缓存）")
        print("  6) 部署构建文件到 Git 仓库")
        print("  7) 导出项目并自动部署")
        print("  0) 退出")
        try:
            choice = input("\n请选择 [0]: ").strip() or "0"
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0

        if choice == "0":
            print("再见。")
            return 0
        if choice == "1":
            project_dir = _prompt_project_dir(engine_dir)
            if project_dir:
                _run_validate(project_dir)
            continue
        if choice == "2":
            if not _run_build_template(engine_dir):
                return 1
            continue
        if choice == "3":
            project_dir = _prompt_project_dir(engine_dir)
            if not project_dir:
                continue
            print("\n--- 校验导出配置 ---")
            if not validate_export_config(project_dir):
                continue
            if not _run_export(engine_dir, project_dir):
                return 1
            continue
        if choice == "4":
            if not _run_build_template(engine_dir):
                return 1
            project_dir = _prompt_project_dir(engine_dir)
            if not project_dir:
                continue
            print("\n--- 校验导出配置 ---")
            if not validate_export_config(project_dir):
                continue
            if not _run_export(engine_dir, project_dir):
                return 1
            continue
        if choice == "5":
            if not _run_build_template(engine_dir, clean=True):
                return 1
            continue
        if choice == "6":
            if not _deploy_to_git():
                return 1
            continue
        if choice == "7":
            project_dir = _prompt_project_dir(engine_dir)
            if not project_dir:
                continue
            print("\n--- 校验导出配置 ---")
            if not validate_export_config(project_dir):
                continue
            if not _run_export(engine_dir, project_dir):
                return 1
            # 导出成功后，询问是否部署
            try:
                confirm = input("\n导出完成，是否部署到 Git 仓库？[Y/n]: ").strip().lower()
                if not confirm or confirm in ['y', 'yes', '是']:
                    # 获取导出路径作为源目录
                    export_path = _get_web_export_path(project_dir)
                    if export_path and export_path.exists():
                        _deploy_to_git(source_dir=export_path)
                    else:
                        _deploy_to_git()
            except (EOFError, KeyboardInterrupt):
                print("\n已跳过部署。")
            continue
        print("无效选项，请重新选择。")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="MyGodotBuild",
        description="Godot Web 导出配置校验与构建/导出自动化",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="项目根目录（含 export_presets.cfg）；校验/导出时必填",
    )
    parser.add_argument(
        "--engine-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Godot 引擎目录（含 scons、bin/）；默认为本脚本所在目录",
    )
    parser.add_argument(
        "--build-template",
        action="store_true",
        help="执行 scons platform=web target=template_release（自动使用所有 CPU 核心）",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="对 --project-dir 执行 Godot --headless --export-release Web",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="仅校验 --project-dir 的导出配置，不构建、不导出",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="构建前先清理缓存（仅与 --build-template 一起使用）",
    )
    parser.add_argument(
        "--no-clean-export",
        action="store_true",
        help="导出前不清理目标文件夹（默认会清理）",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="导出后自动部署到 Git 仓库（需配置 GIT_DEPLOY_REPO）",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="进入交互式菜单（无参数时默认进入）",
    )
    args = parser.parse_args()

    engine_dir = args.engine_dir.resolve()
    if not engine_dir.is_dir():
        print(f"错误: 引擎目录不存在: {engine_dir}", file=sys.stderr)
        return 1

    # 无任何动作参数时，进入交互模式
    if not (args.validate or args.build_template or args.export):
        return run_interactive(engine_dir)
    if args.interactive:
        return run_interactive(engine_dir)

    project_dir = args.project_dir.resolve() if args.project_dir else None
    if args.validate or args.export:
        if not args.project_dir or not args.project_dir.resolve().is_dir():
            print("错误: 校验或导出需指定存在的 --project-dir。", file=sys.stderr)
            return 1
        project_dir = args.project_dir.resolve()

    print(f"引擎目录: {engine_dir}")
    if project_dir:
        print(f"项目目录: {project_dir}")

    if project_dir and (args.validate or args.export):
        print("\n--- 校验导出配置 ---")
        if not validate_export_config(project_dir):
            return 1

    if args.validate:
        print("\n仅校验模式，已退出。")
        return 0

    if args.build_template:
        if not _run_build_template(engine_dir, clean=args.clean, interactive=False):
            return 1

    if args.export:
        if not project_dir:
            print("错误: 导出需指定 --project-dir。", file=sys.stderr)
            return 1
        clean_export = not args.no_clean_export
        if not _run_export(engine_dir, project_dir, clean=clean_export, interactive=False):
            return 1
        
        # 如果指定了 --deploy，自动部署
        if args.deploy:
            export_path = _get_web_export_path(project_dir)
            if export_path and export_path.exists():
                if not _deploy_to_git(source_dir=export_path, interactive=False):
                    return 1
            else:
                if not _deploy_to_git(interactive=False):
                    return 1

    print("\n全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
