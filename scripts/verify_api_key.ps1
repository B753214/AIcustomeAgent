# P5-6 API Key 鉴权验收脚本（需先启动服务：uvicorn app.main:app --reload --port 8000）
# 用法：
#   .\scripts\verify_api_key.ps1
#   .\scripts\verify_api_key.ps1 -BaseUrl "http://127.0.0.1:8000" -ApiKey "your-secret"

param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ApiKey = "test-secret-key"
)

$ErrorActionPreference = "Stop"
$chatBody = @{ message = "你好"; session_id = "auth-smoke" } | ConvertTo-Json -Compress

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [int]$ExpectStatus
    )
    try {
        $resp = & $Action
        $status = [int]$resp.StatusCode
        if ($status -eq $ExpectStatus) {
            Write-Host "[PASS] $Name -> HTTP $status" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] $Name -> 期望 HTTP $ExpectStatus，实际 HTTP $status" -ForegroundColor Red
            if ($resp.Content) { Write-Host "  body: $($resp.Content)" -ForegroundColor DarkYellow }
        }
    } catch {
        $status = [int]$_.Exception.Response.StatusCode.value__
        if ($status -eq $ExpectStatus) {
            Write-Host "[PASS] $Name -> HTTP $status" -ForegroundColor Green
        } else {
            Write-Host "[FAIL] $Name -> 期望 HTTP $ExpectStatus，实际 HTTP $status" -ForegroundColor Red
            Write-Host "  $($_.Exception.Message)" -ForegroundColor DarkYellow
        }
    }
}

Write-Host "`n=== P5-6 API Key 验收 ($BaseUrl) ===" -ForegroundColor Cyan
Write-Host "说明：需在 .env 中设置 API_KEY_ENABLED=true 且 SERVICE_API_KEY=$ApiKey`n"

# 1. 公开接口无需 Key
Invoke-Check "GET /health（无需 Key）" {
    Invoke-WebRequest -Uri "$BaseUrl/health" -Method GET -UseBasicParsing
} -ExpectStatus 200

Invoke-Check "GET /api/v1/stats（无需 Key）" {
    Invoke-WebRequest -Uri "$BaseUrl/api/v1/stats" -Method GET -UseBasicParsing
} -ExpectStatus 200

# 2. 受保护接口：无 Key → 401
Invoke-Check "POST /api/v1/chat 无 Key → 401" {
    Invoke-WebRequest -Uri "$BaseUrl/api/v1/chat" -Method POST `
        -ContentType "application/json" -Body $chatBody -UseBasicParsing
} -ExpectStatus 401

Invoke-Check "POST /api/v1/chat/stream 无 Key → 401" {
    Invoke-WebRequest -Uri "$BaseUrl/api/v1/chat/stream" -Method POST `
        -ContentType "application/json" -Body $chatBody -UseBasicParsing
} -ExpectStatus 401

# 3. 受保护接口：错误 Key → 401
Invoke-Check "POST /api/v1/chat 错误 Key → 401" {
    Invoke-WebRequest -Uri "$BaseUrl/api/v1/chat" -Method POST `
        -ContentType "application/json" -Body $chatBody `
        -Headers @{ "X-API-Key" = "wrong-key" } -UseBasicParsing
} -ExpectStatus 401

# 4. 受保护接口：正确 Key → 200
Invoke-Check "POST /api/v1/chat 正确 Key → 200" {
    Invoke-WebRequest -Uri "$BaseUrl/api/v1/chat" -Method POST `
        -ContentType "application/json" -Body $chatBody `
        -Headers @{ "X-API-Key" = $ApiKey } -UseBasicParsing
} -ExpectStatus 200

Write-Host "`n验收完成。若全部 PASS，P5-6 鉴权链路正常。" -ForegroundColor Cyan
Write-Host "Dashboard：在左侧「API 鉴权」填入相同 Key 后测试聊天/上传。`n"
