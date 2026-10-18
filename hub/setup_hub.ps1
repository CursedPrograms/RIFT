<#
setup_hub.ps1 - make this Windows PC the fleet hub.

  The Ethernet port to the "RIFT" router becomes 192.168.4.1. With an internet uplink (a WiFi
  dongle on your HOME WiFi - never on "RIFT" - or another port), Internet Connection Sharing
  shares it onto that port and hands out the robots' addresses (ICS's ScopeAddress is set to
  192.168.4.1 first, or ICS would pick 192.168.137.1). The router is in Access Point mode: no DHCP
  and no address of its own. With no uplink the port gets a static 192.168.4.1/24, and Windows
  hands out no addresses: put the router in its normal Router mode with its DHCP on instead (RIFT's
  README, "The fleet network"). Either way RIFT runs at 192.168.4.1:5000, the address every robot
  registers with, and the Windows firewall lets the robots reach it.

  .\setup_hub.ps1                      look, say what it would do, ask, then do it (as Administrator)
  .\setup_hub.ps1 -DryRun              only say what it would do (no Administrator needed)
  .\setup_hub.ps1 -Yes                 don't ask
  .\setup_hub.ps1 -Ethernet "Ethernet" -Uplink "Wi-Fi 2"    name the adapters (default: found)
  .\setup_hub.ps1 -Undo                take it all back

  Safe to run again. The router: Mercusys MW302R in Access Point mode, WiFi "RIFT" (WPA2), this
  PC's Ethernet in its WAN port. See RIFT's README and the fleet TODO, section 2.
#>
param(
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$Undo,
    [string]$Ethernet,
    [string]$Uplink
)

$ErrorActionPreference = 'Stop'
$HubIp = '192.168.4.1'
$Port = 5000
$RuleName = 'RIFT fleet hub (TCP 5000)'
$IcsKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters'

function Say($text) { Write-Host "[hub] $text" }
function Step($text, [scriptblock]$action) {
    Write-Host "  > $text"
    if (-not $DryRun) { & $action }
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $DryRun -and -not $admin) {
    Say 'Run this as Administrator (or with -DryRun to only look).'
    exit 1
}

# ---------------------------------------------------------------- ICS through its COM API
function Get-Ics {
    $share = New-Object -ComObject HNetCfg.HNetShare
    $out = @()
    foreach ($c in $share.EnumEveryConnection) {
        $props = $share.NetConnectionProps.Invoke($c)
        $out += [pscustomobject]@{ Name = $props.Name; Config = $share.INetSharingConfigurationForINetConnection.Invoke($c) }
    }
    $out
}

function Disable-AllSharing {
    foreach ($c in Get-Ics) {
        if ($c.Config.SharingEnabled) {
            Step "stop sharing on '$($c.Name)'" { $c.Config.DisableSharing() }
        }
    }
}

# ---------------------------------------------------------------- undo
if ($Undo) {
    Say 'Undoing the hub setup.'
    Disable-AllSharing
    if (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) {
        Step "remove firewall rule '$RuleName'" { Remove-NetFirewallRule -DisplayName $RuleName }
    }
    $eth = if ($Ethernet) { Get-NetAdapter -Name $Ethernet -ErrorAction SilentlyContinue } else { $null }
    if ($eth) {
        Step "'$($eth.Name)' back to DHCP" {
            Get-NetIPAddress -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object IPAddress -eq $HubIp | Remove-NetIPAddress -Confirm:$false
            Set-NetIPInterface -InterfaceIndex $eth.ifIndex -Dhcp Enabled
        }
    } else {
        Say "If you gave an adapter a static $HubIp, run again with -Ethernet <name> to put it back on DHCP."
    }
    if ($DryRun) { Say 'Dry run: nothing changed.' } else { Say 'Done. (ScopeAddress stays set: it only matters when ICS is on.)' }
    exit 0
}

# ---------------------------------------------------------------- look
$wired = Get-NetAdapter -Physical | Where-Object { $_.MediaType -eq '802.3' -and $_.InterfaceDescription -notmatch 'Bluetooth|Virtual|VPN' }
$eth = if ($Ethernet) { Get-NetAdapter -Name $Ethernet } else {
    ($wired | Sort-Object @{ e = { $_.Status -ne 'Up' } }, ifIndex | Select-Object -First 1)
}
if (-not $eth) { Say 'No Ethernet adapter found. Plug in the router, or name it: -Ethernet "Ethernet"'; exit 1 }

$up = if ($Uplink) { Get-NetAdapter -Name $Uplink } else {
    $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Where-Object { $_.ifIndex -ne $eth.ifIndex } |
        Sort-Object { $_.RouteMetric + (Get-NetIPInterface -InterfaceIndex $_.ifIndex -AddressFamily IPv4).InterfaceMetric } |
        Select-Object -First 1
    if ($route) { Get-NetAdapter -InterfaceIndex $route.ifIndex } else { $null }
}

Say "Ethernet port to the router: '$($eth.Name)' ($($eth.InterfaceDescription), $($eth.Status))"
if (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -InterfaceIndex $eth.ifIndex -ErrorAction SilentlyContinue) {
    Say "WARNING: '$($eth.Name)' is this PC's internet right now. After this it's the robots' network:"
    Say "         plug it into the RIFT router, and get internet from another adapter (a WiFi dongle)."
}
if ($up) {
    Say "Internet uplink: '$($up.Name)' ($($up.InterfaceDescription)): ICS shares it onto '$($eth.Name)' as $HubIp"
    $ssid = (netsh wlan show interfaces | Select-String -Pattern "^\s*SSID\s*:\s*(.+)$" | ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() })
    if ($ssid -contains 'RIFT') {
        Say "WARNING: a WiFi adapter is joined to 'RIFT'. The uplink must stay on your HOME WiFi: this PC is on"
        Say "         RIFT through the Ethernet cable. Join the dongle to your home WiFi, then run this again."
    }
} else {
    Say "No internet uplink: '$($eth.Name)' gets a static $HubIp/24, and Windows hands out no addresses:"
    Say "  put the router in its normal Router mode with its DHCP on (RIFT's README, 'The fleet network')."
}
$scope = (Get-ItemProperty -Path $IcsKey -Name ScopeAddress -ErrorAction SilentlyContinue).ScopeAddress
Say "ICS ScopeAddress now: $(if ($scope) { $scope } else { 'not set (ICS would use 192.168.137.1)' })"
$rule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
Say "Firewall rule for TCP $($Port): $(if ($rule) { 'already there' } else { 'to add' })"

if ($DryRun) { Say 'Dry run: the steps it would take:' }
elseif (-not $Yes) {
    $answer = Read-Host '[hub] Go ahead? [y/N]'
    if ($answer -notmatch '^(y|yes)$') { Say 'Nothing changed.'; exit 0 }
}

# ---------------------------------------------------------------- do
if ($up) {
    foreach ($name in 'ScopeAddress', 'ScopeAddressBackup') {
        Step "ICS $name = $HubIp" { Set-ItemProperty -Path $IcsKey -Name $name -Value $HubIp -Type String }
    }
    Disable-AllSharing                                   # ICS shares one connection onto one other
    $ics = Get-Ics
    $pub = $ics | Where-Object Name -eq $up.Name
    $priv = $ics | Where-Object Name -eq $eth.Name
    if (-not $pub -or -not $priv) { throw "ICS doesn't list '$($up.Name)' and '$($eth.Name)'" }
    Step "share '$($up.Name)' (public)" { $pub.Config.EnableSharing(0) }
    Step "onto '$($eth.Name)' (private, $HubIp)" { $priv.Config.EnableSharing(1) }
} else {
    $has = Get-NetIPAddress -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object IPAddress -eq $HubIp
    if (-not $has) {
        Step "'$($eth.Name)' static $HubIp/24" {
            Set-NetIPInterface -InterfaceIndex $eth.ifIndex -Dhcp Disabled
            Get-NetIPAddress -InterfaceIndex $eth.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Remove-NetIPAddress -Confirm:$false
            New-NetIPAddress -InterfaceIndex $eth.ifIndex -IPAddress $HubIp -PrefixLength 24 | Out-Null
        }
    }
}
if (-not $rule) {
    Step "firewall: allow TCP $Port in (RIFT)" {
        New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Any | Out-Null
    }
}

if ($DryRun) { Say 'Dry run: nothing changed.'; exit 0 }
Say "Done. This PC is $HubIp on '$($eth.Name)'; start RIFT (run.bat) and it's at http://$($HubIp):$Port/"
Say "Undo: .\setup_hub.ps1 -Undo -Ethernet '$($eth.Name)'"
