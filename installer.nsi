; ============================================================
; NSIS Unicode

!define APPNAME "ShuiKeKuaiDa"
!define APPVERSION "1.2.0"
!define PUBLISHER "GeorgeChou"

Name "水课快答 ${APPVERSION}"
OutFile "dist_installer\水课快答_Setup_v${APPVERSION}.exe"
InstallDir "$PROGRAMFILES64\水课快答"
InstallDirRegKey HKLM "Software\ShuiKeKuaiDa" ""
RequestExecutionLevel admin
SetCompressor /SOLID lzma
Unicode true

!include "MUI2.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "Install"
    SetOutPath "$INSTDIR"
    File /nonfatal "dist\水课快答.exe"
    WriteUninstaller "$INSTDIR\uninstall.exe"

    CreateDirectory "$SMPROGRAMS\水课快答"
    CreateShortCut "$SMPROGRAMS\水课快答\水课快答.lnk" "$INSTDIR\水课快答.exe" "" "$INSTDIR\水课快答.exe" 0
    CreateShortCut "$DESKTOP\水课快答.lnk" "$INSTDIR\水课快答.exe" "" "$INSTDIR\水课快答.exe" 0
    CreateShortCut "$SMPROGRAMS\水课快答\卸载 水课快答.lnk" "$INSTDIR\uninstall.exe"

    WriteRegStr HKLM "Software\ShuiKeKuaiDa" "" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "DisplayName" "水课快答"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "DisplayIcon" "$INSTDIR\水课快答.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "DisplayVersion" "${APPVERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "Publisher" "${PUBLISHER}"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa" "NoRepair" 1
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\水课快答.exe"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"

    Delete "$SMPROGRAMS\水课快答\水课快答.lnk"
    Delete "$SMPROGRAMS\水课快答\卸载 水课快答.lnk"
    RMDir "$SMPROGRAMS\水课快答"

    Delete "$DESKTOP\水课快答.lnk"

    DeleteRegKey HKLM "Software\ShuiKeKuaiDa"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\ShuiKeKuaiDa"
SectionEnd
