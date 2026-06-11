<#
.SYNOPSIS
    水课快答 - 启动器
.DESCRIPTION
    自动检测环境、安装依赖、下载模型、创建快捷方式、启动主程序。
    使用方式：右键 start.ps1 -> "使用 PowerShell 运行"
#>

$APP_NAME = '水课快答'
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$LOGO_PATH = Join-Path $SCRIPT_DIR 'logo.ico'
$MAIN_SCRIPT = Join-Path $SCRIPT_DIR 'main.pyw'
$REQUIREMENTS = Join-Path $SCRIPT_DIR 'requirements.txt'

$host.UI.RawUI.WindowTitle = "$APP_NAME 启动器"

function Write-Step($num, $text) {
    Write-Host "`n============================================" -ForegroundColor Cyan
    Write-Host "  [$num/5] $text" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
}

function Show-Ask($title, $msg) {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    $r = [System.Windows.Forms.MessageBox]::Show($msg, "$APP_NAME - $title", 'YesNo', 'Question')
    return $r -eq [System.Windows.Forms.DialogResult]::Yes
}

function Show-Info($title, $msg) {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show($msg, "$APP_NAME - $title", 'OK', 'Information') | Out-Null
}

function Show-Error($title, $msg) {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show($msg, "$APP_NAME - $title", 'OK', 'Error') | Out-Null
}

# 全局异常捕获，确保窗口不会闪退
trap {
    Write-Host "`n[错误] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[详细信息] $($_.ScriptStackTrace)" -ForegroundColor DarkYellow
    Write-Host ''
    Show-Error '运行出错' "启动器遇到错误：`n`n$($_.Exception.Message)"
    Read-Host '按回车键关闭此窗口'
    exit 1
}

# ============================================================
#   Step 1: Python 环境
# ============================================================
Write-Step 1 '检测 Python 环境'

$pythonwExe = $null

try {
    $ver = & python --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Python 未安装' }
    Write-Host "  [OK] $ver" -ForegroundColor Green

    $pyDir = Split-Path (Get-Command python -ErrorAction Stop).Source -Parent
    $candidate = Join-Path $pyDir 'pythonw.exe'
    if (Test-Path $candidate) {
        $pythonwExe = $candidate
        Write-Host "  [OK] pythonw.exe: $pythonwExe" -ForegroundColor Green
    } else {
        $pythonwExe = Join-Path $pyDir 'python.exe'
        Write-Host "  [WARN] pythonw.exe 未找到，将使用 python.exe" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [X] 未检测到 Python" -ForegroundColor Red
    Show-Error 'Python 未安装' @'
未检测到 Python 3.9+ 环境。

推荐从微软商店安装（最简单，自动加入 PATH）：
  开始菜单搜索 "Python" → 选择 Python 3.13 安装

或手动下载：
  - 官网: https://www.python.org/downloads/
  - 国内镜像: https://mirrors.aliyun.com/python/

安装完成后重新运行本启动器。
'@
    # 优先尝试打开微软商店 Python 3.13 页面
    try {
        Start-Process 'ms-windows-store://pdp/?productid=9PNRBTZXMB4Z'
    } catch {
        Start-Process 'https://www.python.org/downloads/'
    }
    Read-Host '按回车键退出'
    exit 1
}

# ============================================================
#   Step 2: 依赖检查与安装
# ============================================================
Write-Step 2 '检测 Python 依赖'

$deps = @(
    @{ Name = 'PyQt5';     Import = 'PyQt5'     },
    @{ Name = 'Pillow';    Import = 'PIL'       },
    @{ Name = 'openai';    Import = 'openai'    },
    @{ Name = 'httpx';     Import = 'httpx'     },
    @{ Name = 'pyautogui'; Import = 'pyautogui' },
    @{ Name = 'keyboard';  Import = 'keyboard'  },
    @{ Name = 'paddle';    Import = 'paddle'    },
    @{ Name = 'paddleocr'; Import = 'paddleocr' },
    @{ Name = 'paddlex';   Import = 'paddlex'   }
)

$missing = @()
foreach ($d in $deps) {
    Write-Host "  检测 $($d.Name) ..." -NoNewline
    $null = & python -c "import $($d.Import)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host ' [OK]' -ForegroundColor Green
    } else {
        Write-Host ' [缺失]' -ForegroundColor Red
        $missing += $d.Name
    }
}

if ($missing.Count -gt 0) {
    Write-Host "`n  缺失依赖: $($missing -join ', ')" -ForegroundColor Yellow
    $ok = Show-Ask '安装依赖' "以下依赖缺失，是否立即安装？`n`n$($missing -join '`n')`n`n(paddlepaddle-gpu 体积较大，可能需要几分钟)"
    if (-not $ok) {
        $pipInfo = @"
缺少必要依赖，程序无法启动。

手动安装方法：按 Win+R，输入 cmd 回车，然后粘贴：

pip install PyQt5 Pillow openai httpx pyautogui keyboard paddlepaddle-gpu paddleocr paddlex -i https://mirrors.aliyun.com/pypi/simple

如果失败，换源试试：
pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple

requirements.txt 文件就在本程序目录下。
"@
        Show-Info '无法启动' $pipInfo
        Read-Host '按回车键退出'
        exit 1
    }
    Write-Host "`n  正在安装依赖（多镜像自动切换）..." -ForegroundColor Cyan
    Write-Host '  ----------------------------------------'

    $mirrors = @(
        @{ Name = '阿里云';   Url = 'https://mirrors.aliyun.com/pypi/simple';         Host = 'mirrors.aliyun.com'        },
        @{ Name = '腾讯云';   Url = 'https://mirrors.cloud.tencent.com/pypi/simple';  Host = 'mirrors.cloud.tencent.com' },
        @{ Name = '华为云';   Url = 'https://repo.huaweicloud.com/repository/pypi/simple'; Host = 'repo.huaweicloud.com'  },
        @{ Name = '清华大学'; Url = 'https://pypi.tuna.tsinghua.edu.cn/simple';        Host = 'pypi.tuna.tsinghua.edu.cn'  },
        @{ Name = '中科大';   Url = 'https://pypi.mirrors.ustc.edu.cn/simple';         Host = 'pypi.mirrors.ustc.edu.cn'   }
    )

    $installed = $false
    foreach ($m in $mirrors) {
        Write-Host "  尝试 $($m.Name) 镜像..." -ForegroundColor Cyan
        & python -m pip install -r $REQUIREMENTS -i $m.Url --trusted-host $m.Host 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] 从 $($m.Name) 镜像安装成功" -ForegroundColor Green
            $installed = $true
            break
        } else {
            Write-Host "  [WARN] $($m.Name) 镜像失败，尝试下一个..." -ForegroundColor Yellow
        }
    }

    if (-not $installed) {
        Write-Host "  [WARN] 所有国内镜像失败，尝试官方源..." -ForegroundColor Yellow
        & python -m pip install -r $REQUIREMENTS 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Show-Error '安装失败' @'
依赖自动安装失败（所有镜像均不可用）。

请手动安装：按 Win+R，输入 cmd 回车，然后复制粘贴以下命令：

pip install PyQt5 Pillow openai httpx pyautogui keyboard paddlepaddle-gpu paddleocr paddlex -i https://mirrors.aliyun.com/pypi/simple

如果上面的命令也失败，试试其他镜像：
pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

requirements.txt 文件就在本程序目录下。
安装完成后重新运行本启动器。
'@
            Read-Host '按回车键退出'
            exit 1
        }
        Write-Host "  [OK] 从官方源安装成功" -ForegroundColor Green
    }
    Write-Host "  [OK] 依赖安装完成" -ForegroundColor Green
}

# ============================================================
#   Step 3: OCR 模型
# ============================================================
Write-Step 3 '检测 OCR 模型'

$modelRoot = Join-Path $env:USERPROFILE '.paddlex\official_models'
$modelDet  = Join-Path $modelRoot 'PP-OCRv5_server_det'
$modelRec  = Join-Path $modelRoot 'PP-OCRv5_server_rec'
$modelsOk  = (Test-Path $modelDet) -and (Test-Path $modelRec)

if (-not $modelsOk) {
    Write-Host "  [WARN] OCR 模型尚未下载" -ForegroundColor Yellow
    $ok = Show-Ask '下载模型' "OCR 模型尚未下载（约 100MB）。`n模型托管在百度智能云 BOS，国内访问流畅。`n`n是否立即自动下载？`n（选择"否"可查看手动下载教程）"
    if (-not $ok) {
        $manualInfo = @"
缺少 OCR 模型，程序无法启动。

手动下载方法：
1. 下载以下 5 个文件（浏览器直接打开）：
   https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_server_det_infer.tar
   https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_server_rec_infer.tar
   https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_doc_ori_infer.tar
   https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_textline_ori_infer.tar
   https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/UVDoc_infer.tar

2. 解压到：$env:USERPROFILE\.paddlex\official_models\

3. 确保目录结构如：
   .paddlex\official_models\PP-OCRv5_server_det\（含 .pdiparams 文件）
   .paddlex\official_models\PP-OCRv5_server_rec\（含 .pdiparams 文件）
   ...以此类推

完成后重新运行本启动器。
"@
        Show-Info '无法启动' $manualInfo
        Read-Host '按回车键退出'
        exit 1
    }
    Write-Host "`n  正在下载 OCR 模型（首次约 100MB，请耐心等待）..." -ForegroundColor Cyan
    Write-Host '  ----------------------------------------'
    $env:PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT = '0'
    $modelDownloadOK = $false
    for ($retry = 1; $retry -le 3; $retry++) {
        if ($retry -gt 1) {
            Write-Host "  [INFO] 第 $retry 次重试（等待 5 秒）..." -ForegroundColor Cyan
            Start-Sleep -Seconds 5
        }
        & python -c 'import os; os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"]="0"; from paddleocr import PaddleOCR; _=PaddleOCR(lang="ch", use_textline_orientation=True); print("DOWNLOAD_OK")' 2>&1
        if ($LASTEXITCODE -eq 0) {
            $modelDownloadOK = $true
            break
        }
        Write-Host "  [WARN] 下载失败，准备重试..." -ForegroundColor Yellow
    }
    if (-not $modelDownloadOK) {
        $manualMsg = @"
OCR 模型自动下载失败（已重试 3 次）。

如果反复失败，请手动下载以下 5 个文件：

【下载地址】（浏览器直接打开即可）
1. https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_server_det_infer.tar
2. https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-OCRv5_server_rec_infer.tar
3. https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_doc_ori_infer.tar
4. https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/PP-LCNet_x1_0_textline_ori_infer.tar
5. https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/UVDoc_infer.tar

【放置位置】
$env:USERPROFILE\.paddlex\official_models\

【操作步骤】
1. 下载上面 5 个 .tar 文件（共约 100MB）
2. 在上述路径下创建 official_models 文件夹（如果没有）
3. 用 7-Zip 或 WinRAR 解压每个 .tar 文件
4. 解压后会得到 5 个文件夹，直接放在 official_models 下

最终目录结构应该是：
  %USERPROFILE%\.paddlex\official_models\
  ├── PP-OCRv5_server_det\
  │   └── inference.pdiparams 等文件
  ├── PP-OCRv5_server_rec\
  │   └── inference.pdiparams 等文件
  ├── PP-LCNet_x1_0_doc_ori\
  │   └── inference.pdiparams 等文件
  ├── PP-LCNet_x1_0_textline_ori\
  │   └── inference.pdiparams 等文件
  └── UVDoc\
      └── inference.pdiparams 等文件

完成后重新运行本启动器即可。
"@
        Show-Error '下载失败' $manualMsg
        Read-Host '按回车键退出'
        exit 1
    }
    Write-Host "  [OK] 模型下载完成" -ForegroundColor Green
} else {
    Write-Host "  [OK] OCR 模型已就绪" -ForegroundColor Green
}

# ============================================================
#   Step 4: 桌面快捷方式
# ============================================================
Write-Step 4 '桌面快捷方式'

$desktop  = [Environment]::GetFolderPath('Desktop')
$shortcut = Join-Path $desktop "$APP_NAME.lnk"

if (Test-Path $shortcut) {
    Write-Host "  [OK] 桌面快捷方式已存在，跳过" -ForegroundColor Green
} else {
    $ok = Show-Ask '创建快捷方式' "所有环境检查通过！`n`n是否在桌面创建「$APP_NAME」快捷方式？`n（使用 logo.ico 作为图标）"
    if ($ok) {
        try {
            $ws = New-Object -ComObject WScript.Shell
            $sc = $ws.CreateShortcut($shortcut)
            $sc.TargetPath       = $pythonwExe
            $sc.Arguments        = "`"$MAIN_SCRIPT`""
            $sc.WorkingDirectory = $SCRIPT_DIR
            if (Test-Path $LOGO_PATH) {
                $sc.IconLocation = "$LOGO_PATH,0"
            }
            $sc.Description = $APP_NAME
            $sc.Save()
            Write-Host "  [OK] 桌面快捷方式已创建" -ForegroundColor Green
        } catch {
            Write-Host "  [WARN] 创建失败: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [INFO] 跳过" -ForegroundColor Cyan
    }
}

# ============================================================
#   Step 5: 启动主程序
# ============================================================
Write-Step 5 '启动主程序'

# 启动前关闭全局严格模式，避免 Start-Process 的非致命警告导致窗口闪退
$origEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'

try {
    $admin = Show-Ask '启动选项' "是否以管理员权限启动？`n`n全局快捷键 F9-F12 需要管理员权限才能生效。`n选择"否"将以普通权限启动。"

    if ($admin) {
        Write-Host "  正在请求管理员权限..." -ForegroundColor Cyan
        $proc = Start-Process -FilePath $pythonwExe -ArgumentList "`"$MAIN_SCRIPT`"" -Verb runAs -PassThru -ErrorAction Stop
        Write-Host "  [OK] 请在弹出的 UAC 窗口中确认" -ForegroundColor Green
    } else {
        Write-Host "  正在启动..." -ForegroundColor Cyan
        Start-Process -FilePath $pythonwExe -ArgumentList "`"$MAIN_SCRIPT`""
        Write-Host "  [OK] $APP_NAME 已启动" -ForegroundColor Green
    }
} catch {
    Write-Host "  [X] 启动失败: $($_.Exception.Message)" -ForegroundColor Red
    Show-Error '启动失败' "主程序启动失败：`n`n$($_.Exception.Message)"
} finally {
    # 恢复原始错误处理策略
    $ErrorActionPreference = $origEAP
}

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  $APP_NAME 启动完毕" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ''
Read-Host '按回车键关闭此窗口'
