param(
    [string]$BaseUrl = "http://localhost:8080",
    [string]$CanonicalBaseUrl = "https://riob.us",
    [string]$LineToken = "LECD137"
)

$ErrorActionPreference = "Stop"

function Assert-Contains {
    param(
        [string]$Haystack,
        [string]$Needle,
        [string]$Message
    )

    if ($Haystack -notmatch [regex]::Escape($Needle)) {
        throw "FAIL: $Message (missing: $Needle)"
    }
}

$base = $BaseUrl.TrimEnd("/")
$canonicalBase = $CanonicalBaseUrl.TrimEnd("/")
$linePath = "/linhas/$LineToken"

Write-Host "[1/4] Checking robots endpoint..."
$robots = curl.exe -sS "$base/robots.txt"
Assert-Contains -Haystack $robots -Needle "User-agent: *" -Message "robots header"
Assert-Contains -Haystack $robots -Needle "Sitemap:" -Message "robots sitemap reference"
Write-Host "OK robots"

Write-Host "[2/4] Checking sitemap endpoint..."
$sitemap = curl.exe -sS "$base/sitemap.xml"
Assert-Contains -Haystack $sitemap -Needle "<urlset" -Message "sitemap xml root"
Assert-Contains -Haystack $sitemap -Needle "<loc>" -Message "sitemap loc"
Write-Host "OK sitemap"

Write-Host "[3/4] Checking canonical redirects..."
$h1 = curl.exe -sSI "$base/?linha=$LineToken"
Assert-Contains -Haystack $h1 -Needle "301" -Message "query to line redirect status"
Assert-Contains -Haystack $h1 -Needle "Location: $linePath" -Message "query to line redirect location"

# Verify new routes return 200
$h2 = curl.exe -sSI "$base/veiculos"
Assert-Contains -Haystack $h2 -Needle "200" -Message "veiculos route status"
$h3 = curl.exe -sSI "$base/trajetos"
Assert-Contains -Haystack $h3 -Needle "200" -Message "trajetos route status"

Write-Host "OK routes and redirects"

Write-Host "[4/4] Checking line page metadata..."
$lineHtml = curl.exe -sS "$base$linePath"
Assert-Contains -Haystack $lineHtml -Needle "$canonicalBase$linePath" -Message "canonical URL value"
Assert-Contains -Haystack $lineHtml -Needle 'id="canonical-link"' -Message "canonical tag present"
Assert-Contains -Haystack $lineHtml -Needle 'property="og:url"' -Message "og:url tag present"
Assert-Contains -Haystack $lineHtml -Needle 'name="description"' -Message "description tag present"
Write-Host "OK line metadata"

Write-Host "SEO smoke checks passed for $base (canonical base: $canonicalBase)"
