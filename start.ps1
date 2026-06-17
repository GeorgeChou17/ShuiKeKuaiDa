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
$LAUNCH_BAT  = Join-Path $SCRIPT_DIR 'launch.bat'
$REQUIREMENTS = Join-Path $SCRIPT_DIR 'requirements.txt'
$SKIP_SHORTCUT_FLAG = Join-Path $SCRIPT_DIR '.skip_shortcut_prompt'
$FIRST_RUN_FLAG = Join-Path $SCRIPT_DIR '.first_run_done'

$host.UI.RawUI.WindowTitle = "$APP_NAME 启动器"

# ============================================================
#   GPU 检测函数
# ============================================================
function Get-CudaVersion {
    <#
    .SYNOPSIS
        检测 NVIDIA GPU 和 CUDA 版本
    .OUTPUTS
        PSCustomObject with properties:
        - HasNvidiaGpu: bool
        - GpuName: string
        - CudaVersion: string (e.g., "12.9", "12.6", "11.8", "unknown")
        - RecommendedPackage: string (pip package spec)
        - RecommendedIndex: string (pip index URL)
    #>
    $result = [PSCustomObject]@{
        HasNvidiaGpu = $false
        GpuName = ""
        CudaVersion = "unknown"
        RecommendedPackage = "paddlepaddle==3.3.0"
        RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cpu/"
        RecommendedName = "CPU"
    }

    try {
        # 检测 NVIDIA GPU
        $nvidiaSmi = & nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [INFO] 未检测到 NVIDIA GPU 或 nvidia-smi 不可用" -ForegroundColor DarkGray
            return $result
        }

        $result.HasNvidiaGpu = $true
        $gpuLine = ($nvidiaSmi | Select-Object -First 1).Trim()
        $result.GpuName = $gpuLine

        # 获取 CUDA 版本
        $cudaOutput = & nvidia-smi 2>&1 | Select-String "CUDA Version"
        if ($cudaOutput) {
            # 从 "CUDA Version: 12.6" 提取版本号
            if ($cudaOutput -match 'CUDA Version:\s*([\d.]+)') {
                $cudaVer = $Matches[1]
                $result.CudaVersion = $cudaVer

                # 映射到 PaddlePaddle 支持的 CUDA 版本
                $major = [int]($cudaVer.Split('.')[0])
                $minor = [int]($cudaVer.Split('.')[1])

                if ($major -ge 13) {
                    # CUDA 13.0+ 使用 cu129 版本（最新支持）
                    $result.RecommendedPackage = "paddlepaddle-gpu==3.3.0"
                    $result.RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cu129/"
                    $result.RecommendedName = "CUDA 12.9"
                } elseif ($major -eq 12 -and $minor -ge 7) {
                    # CUDA 12.7-12.9 使用 cu129
                    $result.RecommendedPackage = "paddlepaddle-gpu==3.3.0"
                    $result.RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cu129/"
                    $result.RecommendedName = "CUDA 12.9"
                } elseif ($major -eq 12 -and $minor -ge 4) {
                    # CUDA 12.4-12.6 使用 cu126
                    $result.RecommendedPackage = "paddlepaddle-gpu==3.3.0"
                    $result.RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cu126/"
                    $result.RecommendedName = "CUDA 12.6"
                } elseif ($major -eq 12 -and $minor -le 3) {
                    # CUDA 12.0-12.3 使用 cu118
                    $result.RecommendedPackage = "paddlepaddle-gpu==3.3.0"
                    $result.RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cu118/"
                    $result.RecommendedName = "CUDA 11.8"
                } elseif ($major -eq 11 -and $minor -ge 8) {
                    # CUDA 11.8+ 使用 cu118
                    $result.RecommendedPackage = "paddlepaddle-gpu==3.3.0"
                    $result.RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cu118/"
                    $result.RecommendedName = "CUDA 11.8"
                } else {
                    # 旧版本 CUDA，建议使用 CPU 版本
                    Write-Host "  [WARN] CUDA $cudaVer 版本过旧，将使用 CPU 版本" -ForegroundColor Yellow
                    $result.RecommendedPackage = "paddlepaddle==3.3.0"
                    $result.RecommendedIndex = "https://www.paddlepaddle.org.cn/packages/stable/cpu/"
                    $result.RecommendedName = "CPU"
                }
            }
        }
    } catch {
        Write-Host "  [WARN] GPU 检测失败: $($_.Exception.Message)" -ForegroundColor Yellow
    }

    return $result
}

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
#   首次启动检测 + 启动菜单
# ============================================================
if (Test-Path $FIRST_RUN_FLAG) {
    # 非首次启动：让用户选择
    Write-Host ''
    Write-Host '  ============================================' -ForegroundColor Cyan
    Write-Host "    $APP_NAME" -ForegroundColor Cyan
    Write-Host '  ============================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  [1] 启动水课快答' -ForegroundColor Green
    Write-Host '  [2] 启动修复程序（环境检测/重新安装依赖）' -ForegroundColor Yellow
    Write-Host '  [3] 检查更新并覆盖安装' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '  15秒内未选择将自动启动水课快答' -ForegroundColor DarkGray
    Write-Host ''

    # 15秒超时选择
    $choice = '1'
    $host.UI.RawUI.FlushInputBuffer()
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host -NoNewline '  请选择 (1/2/3): '
    while ($sw.ElapsedMilliseconds -lt 15000) {
        if ($host.UI.RawUI.KeyAvailable) {
            $key = $host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
            Write-Host $key.Character
            if ($key.Character -eq '2') { $choice = '2' }
            elseif ($key.Character -eq '3') { $choice = '3' }
            else { $choice = '1' }
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($sw.ElapsedMilliseconds -ge 15000) {
        Write-Host '1 (超时)'
    }

    if ($choice -eq '1') {
        # 直接启动主程序（管理员权限）
        Write-Host "`n  正在以管理员权限启动..." -ForegroundColor Cyan
        try {
            # 配置 Qt 插件路径
            $qtPluginPath = & python -c "import PyQt5, os; print(os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'plugins', 'platforms'))" 2>&1
            if ($LASTEXITCODE -eq 0 -and (Test-Path $qtPluginPath)) {
                $env:QT_QPA_PLATFORM_PLUGIN_PATH = $qtPluginPath
            }
            Start-Process -FilePath 'pythonw.exe' -ArgumentList "`"$MAIN_SCRIPT`"" -Verb runAs -ErrorAction Stop
            Write-Host "  [OK] 请在弹出的 UAC 窗口中确认" -ForegroundColor Green
        } catch {
            Write-Host "  [X] 启动失败: $($_.Exception.Message)" -ForegroundColor Red
            Show-Error '启动失败' "主程序启动失败：`n`n$($_.Exception.Message)"
            Read-Host '按回车键关闭此窗口'
        }
        exit 0
    }
    elseif ($choice -eq '3') {
        # 启动更新程序
        Write-Host "`n  正在启动更新程序..." -ForegroundColor Cyan
        $updateScript = Join-Path $SCRIPT_DIR 'update.py'
        if (Test-Path $updateScript) {
            & python $updateScript
            Write-Host "`n  更新程序已退出" -ForegroundColor Cyan
        } else {
            Write-Host "  [ERROR] 更新程序不存在: $updateScript" -ForegroundColor Red
            Show-Error '更新失败' "更新程序文件不存在：`n`n$updateScript"
        }
        Read-Host '按回车键返回'
        exit 0
    }
    # 选择 2：继续执行下面的完整环境检测流程
    Write-Host "`n  进入修复模式..." -ForegroundColor Cyan
} else {
    # 首次启动：创建标记，继续执行完整环境检测
    New-Item -Path $FIRST_RUN_FLAG -ItemType File -Force | Out-Null
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

# 检测 GPU 环境
Write-Host "`n  检测 GPU 环境..." -ForegroundColor Cyan
$gpuInfo = Get-CudaVersion
if ($gpuInfo.HasNvidiaGpu) {
    Write-Host "  [OK] 检测到 NVIDIA GPU: $($gpuInfo.GpuName)" -ForegroundColor Green
    Write-Host "  [OK] CUDA 版本: $($gpuInfo.CudaVersion)" -ForegroundColor Green
    Write-Host "  [OK] 推荐安装: $($gpuInfo.RecommendedName) 版本" -ForegroundColor Green
} else {
    Write-Host "  [INFO] 未检测到 NVIDIA GPU，将使用 CPU 版本" -ForegroundColor Cyan
}

# 检测 Python 包依赖
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
    $ok = Show-Ask '安装依赖' "以下依赖缺失，是否立即安装？`n`n$($missing -join '`n')`n`n将安装 $($gpuInfo.RecommendedName) 版本的 PaddlePaddle`n（可能需要几分钟）"
    if (-not $ok) {
        $pipInfo = @"
缺少必要依赖，程序无法启动。

手动安装方法：按 Win+R，输入 cmd 回车，然后粘贴：

# 安装其他依赖
pip install PyQt5 Pillow openai httpx pyautogui keyboard paddleocr paddlex -i https://mirrors.aliyun.com/pypi/simple

# 安装 PaddlePaddle（根据您的 GPU 选择）
# CPU 版本：
pip install paddlepaddle==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
# CUDA 11.8：
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
# CUDA 12.6：
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
# CUDA 12.9：
pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/

requirements.txt 文件就在本程序目录下。
"@
        Show-Info '无法启动' $pipInfo
        Read-Host '按回车键退出'
        exit 1
    }

    Write-Host "`n  正在安装依赖..." -ForegroundColor Cyan
    Write-Host '  ----------------------------------------'

    # Step 2.1: 安装其他依赖（不含 PaddlePaddle）
    $mirrors = @(
        @{ Name = '阿里云';   Url = 'https://mirrors.aliyun.com/pypi/simple';         Host = 'mirrors.aliyun.com'        },
        @{ Name = '腾讯云';   Url = 'https://mirrors.cloud.tencent.com/pypi/simple';  Host = 'mirrors.cloud.tencent.com' },
        @{ Name = '华为云';   Url = 'https://repo.huaweicloud.com/repository/pypi/simple'; Host = 'repo.huaweicloud.com'  },
        @{ Name = '清华大学'; Url = 'https://pypi.tuna.tsinghua.edu.cn/simple';        Host = 'pypi.tuna.tsinghua.edu.cn'  },
        @{ Name = '中科大';   Url = 'https://pypi.mirrors.ustc.edu.cn/simple';         Host = 'pypi.mirrors.ustc.edu.cn'   }
    )

    $installed = $false
    foreach ($m in $mirrors) {
        Write-Host "  尝试 $($m.Name) 镜像安装其他依赖..." -ForegroundColor Cyan
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

pip install PyQt5 Pillow openai httpx pyautogui keyboard paddleocr paddlex -i https://mirrors.aliyun.com/pypi/simple

requirements.txt 文件就在本程序目录下。
安装完成后重新运行本启动器。
'@
            Read-Host '按回车键退出'
            exit 1
        }
        Write-Host "  [OK] 从官方源安装成功" -ForegroundColor Green
    }

    # Step 2.2: 安装 PaddlePaddle（根据 GPU 版本）
    Write-Host "`n  安装 PaddlePaddle ($($gpuInfo.RecommendedName) 版本)..." -ForegroundColor Cyan
    $paddleInstalled = $false
    $paddlePackage = $gpuInfo.RecommendedPackage
    $paddleIndex = $gpuInfo.RecommendedIndex

    # 尝试从 PaddlePaddle 官方源安装（必须）
    Write-Host "  从 PaddlePaddle 官方源安装..." -ForegroundColor Cyan
    & python -m pip install $paddlePackage -i $paddleIndex --trusted-host "www.paddlepaddle.org.cn" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] PaddlePaddle ($($gpuInfo.RecommendedName)) 安装成功" -ForegroundColor Green
        $paddleInstalled = $true
    } else {
        Write-Host "  [WARN] PaddlePaddle 安装失败，尝试备用源..." -ForegroundColor Yellow
        # 备用：从 PyPI 官方源安装（可能较慢）
        & python -m pip install $paddlePackage 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] PaddlePaddle ($($gpuInfo.RecommendedName)) 安装成功（备用源）" -ForegroundColor Green
            $paddleInstalled = $true
        }
    }

    if (-not $paddleInstalled) {
        $cudaVer = $gpuInfo.CudaVersion
        $manualPaddle = @"
PaddlePaddle 自动安装失败。

请手动安装（二选一）：

GPU 版本（推荐，需要 NVIDIA GPU + CUDA $cudaVer）：
  $paddlePackage -i $paddleIndex

CPU 版本（无 GPU 或 GPU 不兼容时）：
  paddlepaddle==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

完整命令（复制粘贴到 cmd）：
  python -m pip install $paddlePackage -i $paddleIndex

安装完成后重新运行本启动器。
"@
        Show-Error 'PaddlePaddle 安装失败' $manualPaddle
        Read-Host '按回车键退出'
        exit 1
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

function New-AppShortcut($path) {
    try {
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($path)
        $sc.TargetPath       = $LAUNCH_BAT
        $sc.WorkingDirectory = $SCRIPT_DIR
        if (Test-Path $LOGO_PATH) {
            $sc.IconLocation = "$LOGO_PATH,0"
        }
        $sc.Description = $APP_NAME
        $sc.Save()
        return $true
    } catch {
        Write-Host "  [WARN] 创建/更新快捷方式失败: $_" -ForegroundColor Yellow
        return $false
    }
}

if (Test-Path $shortcut) {
    # 快捷方式已存在，检查是否指向 launch.bat
    try {
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($shortcut)
        $currentTarget = $sc.TargetPath
        if ($currentTarget -ne $LAUNCH_BAT) {
            Write-Host "  [INFO] 快捷方式指向旧目标，正在更新为 launch.bat..." -ForegroundColor Cyan
            if (New-AppShortcut $shortcut) {
                Write-Host "  [OK] 快捷方式已更新" -ForegroundColor Green
            }
        } else {
            Write-Host "  [OK] 桌面快捷方式正常（指向 launch.bat）" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [WARN] 读取快捷方式失败: $_" -ForegroundColor Yellow
    }
} else {
    # 无快捷方式，询问是否创建（记住用户拒绝）
    if (-not (Test-Path $SKIP_SHORTCUT_FLAG)) {
        $ok = Show-Ask '创建快捷方式' "是否在桌面创建「$APP_NAME」快捷方式？`n（使用 logo.ico 作为图标，指向 launch.bat）"
        if ($ok) {
            if (New-AppShortcut $shortcut) {
                Write-Host "  [OK] 桌面快捷方式已创建" -ForegroundColor Green
            }
        } else {
            # 用户拒绝，创建标记文件，以后不再询问
            New-Item -Path $SKIP_SHORTCUT_FLAG -ItemType File -Force | Out-Null
            Write-Host "  [INFO] 已记住不再询问" -ForegroundColor Cyan
        }
    } else {
        Write-Host "  [INFO] 跳过（用户已选择不再创建）" -ForegroundColor Cyan
    }
}

# ============================================================
#   Step 5: 启动主程序（管理员权限 + 自动关闭窗口）
# ============================================================
Write-Step 5 '启动主程序'

# 修复 Qt 平台插件找不到的问题（qwindows.dll）
Write-Host "  配置 Qt 平台插件路径..." -ForegroundColor Cyan
$qtPluginPath = & python -c "import PyQt5, os; print(os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'plugins', 'platforms'))" 2>&1
if ($LASTEXITCODE -eq 0 -and (Test-Path $qtPluginPath)) {
    $env:QT_QPA_PLATFORM_PLUGIN_PATH = $qtPluginPath
    Write-Host "  [OK] Qt 插件路径: $qtPluginPath" -ForegroundColor Green
} else {
    Write-Host "  [WARN] 未找到 Qt 插件路径，程序可能无法启动" -ForegroundColor Yellow
}

# 启动前关闭全局严格模式，避免 Start-Process 的非致命警告导致窗口闪退
$origEAP = $ErrorActionPreference
$ErrorActionPreference = 'Continue'

try {
    Write-Host "  正在以管理员权限启动..." -ForegroundColor Cyan
    Start-Process -FilePath $pythonwExe -ArgumentList "`"$MAIN_SCRIPT`"" -Verb runAs -ErrorAction Stop
    Write-Host "  [OK] 请在弹出的 UAC 窗口中确认" -ForegroundColor Green

    # 等待程序窗口出现（最多 30 秒）
    Write-Host "  等待程序窗口启动..." -ForegroundColor Cyan
    $timeout = 30
    $elapsed = 0
    $windowFound = $false
    while ($elapsed -lt $timeout) {
        Start-Sleep -Seconds 1
        $elapsed++
        $win = Get-Process | Where-Object { $_.MainWindowTitle -like '*水课快答*' } | Select-Object -First 1
        if ($win) {
            $windowFound = $true
            Write-Host "  [OK] 程序窗口已启动，自动关闭启动器" -ForegroundColor Green
            break
        }
    }

    if (-not $windowFound) {
        Write-Host "  [WARN] 未检测到程序窗口（可能已在后台运行）" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [X] 启动失败: $($_.Exception.Message)" -ForegroundColor Red
    Show-Error '启动失败' "主程序启动失败：`n`n$($_.Exception.Message)"
    Read-Host '按回车键关闭此窗口'
} finally {
    $ErrorActionPreference = $origEAP
}

# 自动关闭 PowerShell 窗口
exit 0
