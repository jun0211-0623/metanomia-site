param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# Public profile data supplied in Metanomia (1).xlsx on 2026-08-19.
# Existing reports, books, roles, portraits, and other profile content are left untouched.
$profiles = @(
  @{ Name='김상환'; Slug='sanghwan-kim'; Email='kimsanghwan99@gmail.com' },
  @{ Name='김세린'; Slug='serin-kim'; Email='rene426@naver.com' },
  @{ Name='김연경'; Slug='yonkyung-kim'; Email='pola031316@gmail.com' },
  @{ Name='김유정'; Slug='yujeong-kim'; Email='Liuting1004@gmail.com' },
  @{ Name='김은미'; Slug='eunmi-kim'; Email='kimem1level@gmail.com' },
  @{ Name='노성준'; Slug='seongjun-noh'; Email='noeeo111@gmail.com' },
  @{ Name='류제우'; Slug='jewoo-ryu'; Email='jw.orbit1@gmail.com'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='박민구'; Slug='mingu-park'; Email='mingupark1221@gmail.com'; EducationKo=@('2026.03 ~ 현재 한양대학교 비트코인화폐철학과 석사과정 재학','2016.09 ~ 2023.02 고려대학교 KU-KIST융합대학원 이학박사(신경과학 전공)','2010.03 ~ 2016.08 고려대학교 바이오의공학부 공학사'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University (Mar. 2026–present)','Ph.D. in Neuroscience, KU-KIST Graduate School of Converging Science and Technology, Korea University (Sep. 2016–Feb. 2023)','B.Eng. in Biomedical Engineering, Korea University (Mar. 2010–Aug. 2016)'); CareerKo=@('2023.03 ~ 2025.09 기초과학연구원(IBS) 기억 및 교세포 연구단, 박사 후 연구원'); CareerEn=@('Postdoctoral Researcher, Memory and Glia Research Group, Institute for Basic Science (IBS) (Mar. 2023–Sep. 2025)') },
  @{ Name='박보영'; Slug='boyoung-park'; Email='parkbo0@hanyang.ac.kr'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','서강대학교 전자공학과 졸업'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.S. in Electronic Engineering, Sogang University'); CareerKo=@('前 삼성전자 LCD 사업부(現 삼성디스플레이) 연구개발','前 LG전자 전략구매팀'); CareerEn=@('Former R&D, LCD Business, Samsung Electronics (now Samsung Display)','Former Strategic Procurement Team, LG Electronics') },
  @{ Name='박상현'; Slug='sanghyeon-park'; Email='kaistbab11@gmail.com'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='박선협'; Slug='seonhyeop-park'; Email='821psh@gmail.com' },
  @{ Name='박수훈'; Slug='suhoon-park'; Email='tngns0011@gmail.com'; LinkedIn='https://www.linkedin.com/in/suhoon-park/'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','Liberty University, Finance'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.S. in Finance, Liberty University'); CareerKo=@('보험연수원 크립토스쿨 강사','세림종합물류 국제영업부'); CareerEn=@('Instructor, Crypto School, Korea Insurance Institute','International Sales, Serim Total Logistics') },
  @{ Name='박시우'; Slug='siwoo-park'; Email='ciwoolove@gmail.com'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='석민국'; Slug='minguk-seok'; Email='brdonverja@gmail.com' },
  @{ Name='손혜민'; Slug='hyemin-son'; Email='hyeomin0109@gmail.com'; LinkedIn='https://www.linkedin.com/in/hyemin-son-20a319350'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정 재학중','이화여자대학교 약학대학 약학과 학사 졸업','서울대학교 생활과학대학 식품영양학과 학사 졸업'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.Pharm., College of Pharmacy, Ewha Womans University','B.S. in Food and Nutrition, College of Human Ecology, Seoul National University'); CareerKo=@('(주)오태버스','보험연수원 크립토스쿨 교무총괄'); CareerEn=@('OtaVerse Co., Ltd.','Academic Operations Lead, Crypto School, Korea Insurance Institute') },
  @{ Name='유주아'; Slug='zooa-yoo'; Email='bitmoong2040@gmail.com' },
  @{ Name='이정은'; Slug='jungeun-lee'; Email='emailkristinlee@gmail.com' },
  @{ Name='이지환'; Slug='jeehwan-lee'; Email='jeehwanlee27@gmail.com' },
  @{ Name='이창준'; Slug='changjun-lee'; Email='johan000623@gmail.com'; LinkedIn='https://www.linkedin.com/in/changjun-lee'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); CareerKo=@('(주)모비커스'); CareerEn=@('Mobickers Co., Ltd.') },
  @{ Name='조세연'; Slug='seyeon-cho'; Email='csy9512@naver.com' },
  @{ Name='조용래'; Slug='yongrae-cho'; Email='dragoncyr46@gmail.com' },
  @{ Name='진성훈'; Slug='sunghoon-jin'; Email='shjin0130@gmail.com' },
  @{ Name='진승주'; Slug='seungju-jin'; Email='gufudu1234@gmail.com'; LinkedIn='https://www.linkedin.com/in/seungjoojin' },
  @{ Name='윤성아'; Slug='sungah-yoon'; Email='seongah7865@gmail.com'; LinkedIn='https://www.linkedin.com/in/seongahyoun'; EducationKo=@('서울대학교 미술대학 디자인학부 석사과정 재학','홍익대학교 미술대학 산업디자인학과 졸업'); EducationEn=@('M.A. candidate, Department of Design, College of Fine Arts, Seoul National University','B.F.A. in Industrial Design, College of Fine Arts, Hongik University') },
  @{ Name='정두루'; Slug='dooroo-chung'; Email='doorooch@gmail.com'; LinkedIn='https://www.linkedin.com/in/dooroo-chung/'; EducationKo=@('University of Southern California. B.S. Architectural Studies'); EducationEn=@('B.S. in Architectural Studies, University of Southern California'); CareerKo=@('모비커스(주)'); CareerEn=@('Mobickers Co., Ltd.') },
  @{ Name='한상준'; Slug='sangjun-han'; Email='samueljhan@naver.com'; LinkedIn='https://www.linkedin.com/in/samuel-j-hahn-2a9149262/en'; EducationKo=@('한국외대 마인어과 학사'); EducationEn=@('B.A. in Malay-Indonesian Studies, Hankuk University of Foreign Studies') }
)

function Encode([string]$Value) { [System.Net.WebUtility]::HtmlEncode($Value) }

function DetailBlock([string]$Label, $Values, [string]$Modifier = '') {
  if ($null -eq $Values -or @($Values).Count -eq 0) { return '' }
  $items = @($Values) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  if ($items.Count -eq 0) { return '' }
  $content = ($items | ForEach-Object { '              <span>' + (Encode $_) + '</span>' }) -join "`r`n"
  @"
          <div class="profile__detail$Modifier">
            <dt>$(Encode $Label)</dt>
            <dd>
$content
            </dd>
          </div>
"@
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
$actionsPattern = [regex]::new('<div class="profile__actions">.*?</div>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
$generatedPattern = [regex]::new('\s*<!-- PROFILE DETAILS FROM METANOMIA\.XLSX -->.*?<!-- /PROFILE DETAILS FROM METANOMIA\.XLSX -->', [System.Text.RegularExpressions.RegexOptions]::Singleline)
$updated = 0

foreach ($profile in $profiles) {
  foreach ($locale in @('ko', 'en')) {
    $relative = if ($locale -eq 'ko') { "ko/people/{0}.html" } else { "people/{0}.html" }
    $path = Join-Path $ProjectRoot ($relative -f $profile.Slug)
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing profile page: $path" }
    $html = [System.IO.File]::ReadAllText($path)
    $html = $generatedPattern.Replace($html, '')

    $actions = @"
<div class="profile__actions">
            <a class="btn btn--ghost" href="mailto:$(Encode $profile.Email)">$(Encode $profile.Email)</a>
"@
    if ($profile.LinkedIn) {
      $actions += "`r`n            <a class=`"btn btn--ghost`" href=`"$(Encode $profile.LinkedIn)`" target=`"_blank`" rel=`"noopener noreferrer`">LinkedIn ↗</a>"
    }
    $actions += "`r`n          </div>"
    if (-not $actionsPattern.IsMatch($html)) { throw "Profile actions not found: $path" }
    $html = $actionsPattern.Replace($html, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $actions }, 1)

    $education = if ($locale -eq 'ko') { $profile.EducationKo } else { $profile.EducationEn }
    $career = if ($locale -eq 'ko') { $profile.CareerKo } else { $profile.CareerEn }
    $labels = if ($locale -eq 'ko') { @{ Education='학력'; Career='경력' } } else { @{ Education='Education'; Career='Career' } }

    $detailsBody = ''
    $detailsBody += DetailBlock $labels.Education $education
    $detailsBody += DetailBlock $labels.Career $career

    if ($detailsBody) {
      $details = @"

          <!-- PROFILE DETAILS FROM METANOMIA.XLSX -->
          <dl class="profile__details">
$detailsBody          </dl>
          <!-- /PROFILE DETAILS FROM METANOMIA.XLSX -->
"@
      $html = $actionsPattern.Replace($html, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $m.Value + $details }, 1)
    }

    $html = [regex]::Replace($html, 'style\.css\?v=[^"'']+', 'style.css?v=20260818-profile-sync')
    [System.IO.File]::WriteAllText($path, $html, $utf8)
    $updated++
  }
}

Write-Host "Updated $updated localized profile pages from Metanomia.xlsx data."
