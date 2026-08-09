$ErrorActionPreference = 'Stop'

$patterns = @(
  'sk-[A-Za-z0-9_-]{16,}',
  'DASHSCOPE_API_KEY\s*=\s*[^\s#][^\s]*',
  'POSTGRES_PASSWORD\s*=\s*(?!这里填写|CHANGE_ME|your_|<)[^\s#][^\s]*',
  'SMTP_PASSWORD\s*=\s*(?!CHANGE_ME|your_|<)[^\s#][^\s]*',
  'DATABASE_URL\s*=\s*postgres(?:ql)?[^\s#]*:[^\s#]*@'
)

$files = Get-ChildItem -Path $PSScriptRoot\.. -Recurse -File |
  Where-Object {
    $_.FullName -notmatch '\\(node_modules|dist|dist-user|target|\.git|data|\.venv)\\' -and
    $_.Name -notlike '.env*' -and
    $_.Name -ne '.env.example' -and
    $_.Extension -notin @('.png', '.jpg', '.jpeg', '.db')
  }

$found = $false
foreach ($pattern in $patterns) {
  $matches = $files | Select-String -Pattern $pattern
  if ($matches) {
    $found = $true
    $matches | ForEach-Object { Write-Error "Potential secret: $($_.Path):$($_.LineNumber)" }
  }
}

if ($found) { exit 1 }
Write-Output 'No likely secrets found.'
