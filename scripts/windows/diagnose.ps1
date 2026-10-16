# Read-only. No driver installation, firmware writes, TX or RX.
$ErrorActionPreference = 'Continue'
$report = [ordered]@{
    os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture
    cpu = Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
    memory = Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
    gpu = Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion
    disks = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,Size,FreeSpace
    hackrf = @(Get-PnpDevice -PresentOnly | Where-Object {
        $_.InstanceId -match 'VID_1D50&PID_6089'
    } | Select-Object Status,Class,FriendlyName,InstanceId)
}
$report | ConvertTo-Json -Depth 5
$info = Join-Path $PSScriptRoot '..\..\tools\hackrf\Library\bin\hackrf_info.exe'
if (Test-Path $info) { & $info }
