$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
$base = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'io.github.clash-verge-rev.clash-verge-rev'
$stage = 'initialization'

function Find-CorePipe {
    $names = @([IO.Directory]::GetFiles('\\.\pipe\') | Where-Object {
        ($_ -split '\\')[-1] -match '^verge-mihomo($|-)'
    })
    if ($names.Count -ne 1) { return $null }
    return ($names[0] -split '\\')[-1]
}

function Invoke-Core($method, $endpoint, $body = $null) {
    $pipe = [IO.Pipes.NamedPipeClientStream]::new('.', $script:pipeName,
        [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::Asynchronous)
    try {
        $pipe.Connect(2500)
        $payload = ''
        if ($null -ne $body) { $payload = $body | ConvertTo-Json -Compress -Depth 100 }
        $bodyBytes = [Text.Encoding]::UTF8.GetBytes($payload)
        $header = "$method $endpoint HTTP/1.0`r`nHost: localhost`r`nAuthorization: Bearer $script:secret`r`nConnection: close`r`nContent-Type: application/json`r`nContent-Length: $($bodyBytes.Length)`r`n`r`n"
        $headerBytes = [Text.Encoding]::ASCII.GetBytes($header)
        $pipe.Write($headerBytes, 0, $headerBytes.Length)
        if ($bodyBytes.Length) { $pipe.Write($bodyBytes, 0, $bodyBytes.Length) }
        $pipe.Flush()
        $reader = [IO.StreamReader]::new($pipe)
        $read = $reader.ReadToEndAsync()
        if (-not $read.Wait(8000)) { throw 'Core API timeout' }
        $parts = $read.Result -split "`r`n`r`n", 2
        if ($parts[0] -notmatch '^HTTP/\S+ (200|204)') { throw 'Core API rejected request' }
        if ($parts[1].Trim()) { return ($parts[1] | ConvertFrom-Json) }
    } finally { $pipe.Dispose() }
}

try {
    if ($inputData.action -eq 'paths') {
        @{clash_directory=$base; local_appdata=[Environment]::GetFolderPath('LocalApplicationData')} |
            ConvertTo-Json -Compress
        exit 0
    }
    $stage = 'locate_clash'
    $script:pipeName = Find-CorePipe
    if (-not $script:pipeName -and $inputData.start_if_missing) {
        # Launch the installed GUI only when no existing core or GUI is present.
        if (-not (Get-Process -Name 'clash-verge','verge-mihomo' -ErrorAction SilentlyContinue)) {
            $exe = Join-Path $env:ProgramFiles 'Clash Verge\clash-verge.exe'
            $start = [Diagnostics.ProcessStartInfo]::new($exe)
            $start.UseShellExecute = $true
            [void][Diagnostics.Process]::Start($start)
        }
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        do {
            Start-Sleep -Milliseconds 300
            $script:pipeName = Find-CorePipe
        } while (-not $script:pipeName -and [DateTime]::UtcNow -lt $deadline)
    }
    if (-not $script:pipeName) { throw 'No unique running Clash core' }
    $raw = [IO.File]::ReadAllText((Join-Path $base 'clash-verge.yaml'))
    $script:secret = [regex]::Match($raw, '(?m)^secret:\s*([^\r\n]+)').Groups[1].Value.Trim().Trim('"').Trim("'")
    if ($script:secret -match "`r|`n") { throw 'Invalid local controller credential' }

    if ($inputData.action -eq 'apply') {
        $stage = 'apply_listener_configuration'
        Invoke-Core 'PUT' '/configs?force=false' @{payload=$inputData.payload} | Out-Null
        @{ok=$true} | ConvertTo-Json -Compress
        exit 0
    }

    if ($inputData.action -eq 'connection') {
        $stage = 'inspect_probe_route'
        $all = Invoke-Core 'GET' '/connections'
        $matched = @($all.connections | Where-Object {
            [string]$_.metadata.sourcePort -eq [string]$inputData.source_port -and
            $_.metadata.host -eq 'api.anthropic.com'
        })
        @{matches=@($matched | ForEach-Object { @{chains=@($_.chains);host=$_.metadata.host} })} |
            ConvertTo-Json -Compress -Depth 6
        exit 0
    }

    $stage = 'inspect_core'
    $version = Invoke-Core 'GET' '/version'
    $configuration = Invoke-Core 'GET' '/configs'
    $allProxies = Invoke-Core 'GET' '/proxies'
    $selected = $allProxies.proxies.PSObject.Properties['PROXY'].Value.now
    if ($inputData.action -eq 'snapshot') {
        @{ok=$true; general=$configuration; selected_node=$selected; version=$version.version} |
            ConvertTo-Json -Compress -Depth 100
        exit 0
    }
    $node = $null
    if ($inputData.node) { $node = $allProxies.proxies.PSObject.Properties[$inputData.node].Value }
    $listeners = @()
    if ($inputData.port) {
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $inputData.port -ErrorAction SilentlyContinue |
            ForEach-Object {
                $owner = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
                @{address=$_.LocalAddress; owner=$owner.ProcessName}
            })
    }
    $result = @{ok=$true; version=$version.version; mode=$configuration.mode;
        selected_node=$selected; node_type=$node.type; listeners=$listeners}

    if ($inputData.action -eq 'browser') {
        $stage = 'launch_login_browser'
        $url = [Uri]$inputData.url
        if ($url.Scheme -ne 'https' -or $inputData.url -match '[\x00-\x20"]') {
            throw 'Only HTTPS login URLs are accepted'
        }
        $directory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ClaudeClashGuard'
        $profile = Join-Path $directory 'ChromeProfile'
        $controller = Join-Path $directory 'browser_controller.cjs'
        $node = Join-Path $env:ProgramFiles 'nodejs\node.exe'
        if (-not (Test-Path -LiteralPath $controller) -or -not (Test-Path -LiteralPath $node)) {
            throw 'Dedicated browser controller is not installed'
        }
        $existing = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
            $_.CommandLine -and $_.CommandLine.Contains($profile) -and $_.CommandLine -notmatch '--type='
        })
        if ($existing.Count) {
            $stage = 'verify_existing_browser_controller'
            $state = Get-Content -LiteralPath (Join-Path $directory 'browser-controller.json') -Raw | ConvertFrom-Json
            $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$state.pid)"
            if (-not $owner -or $owner.Name -ne 'node.exe' -or -not $owner.CommandLine.Contains($controller)) {
                throw 'Close the old dedicated browser before relaunching'
            }
            foreach ($browser in $existing) {
                if (-not $browser.CommandLine.Contains('--remote-debugging-pipe') -or
                    -not $browser.CommandLine.Contains("--proxy-server=http://127.0.0.1:$($inputData.port)") -or
                    -not $browser.CommandLine.Contains('--proxy-bypass-list=<-loopback>') -or
                    -not $browser.CommandLine.Contains('--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1') -or
                    -not $browser.CommandLine.Contains('--lang=en-US')) {
                    throw 'Existing dedicated browser has incompatible launch settings'
                }
            }
        }
        $stage = 'start_browser_controller'
        if (-not $existing.Count) {
            # ShellExecute separates the long-lived server from WSL's interop lifetime.
            $serverStart = [Diagnostics.ProcessStartInfo]::new($node)
            $serverStart.UseShellExecute = $true
            $serverStart.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
            $serverStart.Arguments = '"' + $controller + '" --serve'
            [void][Diagnostics.Process]::Start($serverStart)
        }
        $start = [Diagnostics.ProcessStartInfo]::new($node)
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardInput = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $start.Arguments = '"' + $controller + '"'
        $browserProcess = [Diagnostics.Process]::new()
        $browserProcess.StartInfo = $start
        [void]$browserProcess.Start()
        $browserProcess.StandardInput.Write((@{url=$inputData.url; port=[int]$inputData.port} | ConvertTo-Json -Compress))
        $browserProcess.StandardInput.Close()
        $reply = $browserProcess.StandardOutput.ReadLineAsync()
        if (-not $reply.Wait(25000)) {
            if (-not $browserProcess.HasExited) { $browserProcess.Kill() }
            throw 'Dedicated browser startup timed out'
        }
        $answer = $reply.Result | ConvertFrom-Json
        if (-not $answer.ok) { throw 'Dedicated browser startup verification failed' }
        $result = @{ok=$true; browser_started=$true; browser_reused=[bool]$existing.Count}
    }
    $result | ConvertTo-Json -Compress -Depth 6
} catch {
    # Never return request bodies, account URLs or controller secrets in diagnostics.
    @{ok=$false; stage=$stage; error_type=$_.Exception.GetType().Name} | ConvertTo-Json -Compress
    exit 1
}
