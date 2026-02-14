# CI/CD 构建说明

本仓库配置了 GitHub Actions 自动构建加密的 Web 导出模板。

## 🔐 必需的 GitHub Secrets

在仓库的 Settings > Secrets > Actions 中配置以下 Secret：

| Secret 名称 | 用途 | 格式 |
|------------|------|------|
| `SCRIPT_AES256_ENCRYPTION_KEY` | 用于构建带加密功能的 Web 模板 | 64 位十六进制字符串 |

### 生成加密密钥

使用 Python 生成随机密钥：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

或使用 OpenSSL：

```bash
openssl rand -hex 32
```

## 🚀 使用方法

### 手动触发构建

1. 进入 GitHub 仓库的 Actions 标签页
2. 选择 "🔨 Build Web Template (Encrypted)" workflow
3. 点击 "Run workflow"
4. 选择 Godot 版本（默认 4.6）
5. 等待构建完成（约 30-60 分钟首次构建，后续约 5-10 分钟）

### 下载构建产物

构建完成后会自动创建 GitHub Release，标签格式为 `web-template-v4.6-<build_number>`。

Release 包含：
- `godot.web.template_release.wasm32.nothreads.zip` - Web 导出模板
- `godot.web.template_release.wasm32.nothreads.zip.sha256` - SHA256 校验和

## 🔄 密钥轮换

如果密钥被泄露或需要更换：

1. 生成新的 64 位十六进制密钥
2. 更新 GitHub Secrets 中的 `SCRIPT_AES256_ENCRYPTION_KEY`
3. 重新触发构建 workflow
4. 更新所有使用旧模板的项目

**重要：** 使用旧密钥构建的模板与新密钥不兼容，需要重新导出所有项目。

## 📝 本地构建

如需本地构建（不推荐，建议使用 CI），可以：

1. 配置环境变量：
   ```bash
   export SCRIPT_AES256_ENCRYPTION_KEY="your_64_hex_key_here"
   ```

2. 或创建本地配置文件 `MyGodotBuild.local.toml`（已添加到 .gitignore）：
   ```toml
   encryption_key = "your_64_hex_key_here"
   ```

3. 运行构建脚本：
   ```bash
   python MyGodotBuild.py --build-template
   ```

## ⚠️ 安全提示

- **切勿** 在代码中硬编码密钥
- **切勿** 将密钥提交到 Git
- **定期轮换** 密钥以提高安全性
- **使用不同的密钥** 用于开发和生产环境

## 🔗 相关资源

- [Godot 导出加密文档](https://docs.godotengine.org/en/stable/development/compiling/compiling_for_web.html)
- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [SCons 构建系统](https://scons.org/)
