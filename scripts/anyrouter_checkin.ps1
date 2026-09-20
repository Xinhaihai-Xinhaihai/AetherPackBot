# Refresh the already-open AnyRouter tab in Edge.
# Check-in on anyrouter.top is just a page reload.

$ErrorActionPreference = "Continue"
$Url = "https://anyrouter.top/console/personal"
$LogDir = "D:\AetherPackBot\data\logs"
$LogFile = Join-Path $LogDir "anyrouter_checkin.log"
$Edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Output $line
}

function Refresh-OpenTab {
    Add-Type -AssemblyName UIAutomationClient | Out-Null
    Add-Type -AssemblyName UIAutomationTypes | Out-Null
    Add-Type -AssemblyName System.Windows.Forms | Out-Null

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $winCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Window
    )
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $winCond)
    foreach ($w in $windows) {
        $title = [string]$w.Current.Name
        if ($title -notmatch "Edge") { continue }

        $tabCond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::TabItem
        )
        $tabs = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond)
        foreach ($tab in $tabs) {
            $tabName = [string]$tab.Current.Name
            if ($tabName -notmatch "Any Router|anyrouter|any router") { continue }
            try {
                $sel = $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
                $sel.Select()
            } catch {}
            try { $tab.SetFocus() } catch {}
            try { $w.SetFocus() } catch {}
            Start-Sleep -Milliseconds 280
            [System.Windows.Forms.SendKeys]::SendWait("{F5}")
            return "refreshed-tab:$tabName"
        }

        if ($title -match "Any Router|anyrouter") {
            try { $w.SetFocus() } catch {}
            Start-Sleep -Milliseconds 280
            [System.Windows.Forms.SendKeys]::SendWait("{F5}")
            return "refreshed-window:$title"
        }
    }
    return $null
}

try {
    $hit = Refresh-OpenTab
    if ($hit) {
        Write-Log "OK $hit"
        exit 0
    }
} catch {
    Write-Log "UIA miss: $($_.Exception.Message)"
}

if (Test-Path $Edge) {
    Start-Process -FilePath $Edge -ArgumentList "--profile-directory=Default", $Url
    Write-Log "OK opened-url-in-existing-edge"
    exit 0
}

Write-Log "FAIL edge-not-found"
exit 1
