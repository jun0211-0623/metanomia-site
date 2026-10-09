param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# Public profile data supplied in the Metanomia member roster Google Sheet on 2026-10-09.
# Phone numbers, internal notes, wallet addresses, and file references are intentionally excluded.
# Existing reports, books, roles, portraits, and other profile content are left untouched.
$profiles = @(
  @{ Name='손혜민'; EnglishName='Hyemin Son'; Slug='hyemin-son'; Email='hyeomin0109@gmail.com'; RoleKo='총괄 매니저 · 편집위원 · 연구원'; RoleEn='General Manager · Editorial Board · Researcher'; Image='/images/people/son-hyemin.webp'; LinkedIn='https://www.linkedin.com/in/hyemin-son-20a319350'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','이화여자대학교 약학과 졸업','서울대학교 식품영양학과 졸업'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.Pharm., Ewha Womans University','B.S. in Food and Nutrition, Seoul National University'); CareerKo=@('(주)오태버스','보험연수원 크립토스쿨 교무총괄'); CareerEn=@('OtaVerse Co., Ltd.','Academic Operations Lead, Crypto School, Korea Insurance Institute') },
  @{ Name='박상현'; EnglishName='Sanghyeon Park'; Slug='sanghyeon-park'; Email='kaistbab11@gmail.com'; RoleKo='편집위원 · 연구원'; RoleEn='Editorial Board · Researcher'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='진성훈'; EnglishName='Sunghoon Jin'; Slug='sunghoon-jin'; Email='shjin0130@gmail.com'; RoleKo='편집위원 · 연구원'; RoleEn='Editorial Board · Researcher' },
  @{ Name='김연경'; EnglishName='Yonkyung Kim'; Slug='yonkyung-kim'; Email='pola031316@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; Image='/images/people/kim-yonkyung.webp' },
  @{ Name='김은미'; EnglishName='Eunmi Kim'; Slug='eunmi-kim'; Email='kimem1level@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='박수훈'; EnglishName='Suhoon Park'; Slug='suhoon-park'; Email='tngns0011@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; Image='/images/people/park-suhoon.webp'; LinkedIn='https://www.linkedin.com/in/suhoon-park/'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','Liberty University, Finance'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.S. in Finance, Liberty University'); CareerKo=@('보험연수원 크립토스쿨 강사','세림종합물류 국제영업부'); CareerEn=@('Instructor, Crypto School, Korea Insurance Institute','International Sales, Serim Total Logistics') },
  @{ Name='석대한'; EnglishName='Daehan Seok'; Slug='daehan-seok'; Email='eowjxmdlrmf1@gmail.com'; RoleKo='연구원'; RoleEn='Researcher' },
  @{ Name='석민국'; EnglishName='Minguk Seok'; Slug='minguk-seok'; Email='stoneminguk@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; Image='/images/people/seok-minguk.webp' },
  @{ Name='유주아'; EnglishName='Zooa Yoo'; Slug='zooa-yoo'; Email='bitmoong2040@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='이지환'; EnglishName='Jeehwan Lee'; Slug='jeehwan-lee'; Email='jeehwanlee27@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; EducationKo=@('연세대학교 경영학과 졸업','한양대학교 법학전문대학원 졸업','한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('B.B.A., Yonsei University','J.D., Hanyang University School of Law','M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); CareerKo=@('법률사무소 도전'); CareerEn=@('Challenge Law Office') },
  @{ Name='이창준'; EnglishName='Changjun Lee'; Slug='changjun-lee'; Email='johan000623@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; LinkedIn='https://www.linkedin.com/in/changjun-lee'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); CareerKo=@('(주)모비커스'); CareerEn=@('Mobickers Co., Ltd.') },
  @{ Name='조세연'; EnglishName='Seyeon Jo'; Slug='seyeon-cho'; Email='caoxijuan95@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','가톨릭대학교 중국언어문화 전공 졸업'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.A. in Chinese Language & Culture, The Catholic University of Korea'); CareerKo=@('前 애터미(주) 글로벌운영전략팀'); CareerEn=@('Former, Global Operations Strategy Team, Atomy Co., Ltd.') },
  @{ Name='권준석'; EnglishName='Junseok Kwon'; Slug='junseok-kwon'; Email='rnjswnstjr98@gmail.com'; RoleKo='회원'; RoleEn='Member'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); New=$true },
  @{ Name='권형섭'; EnglishName='DK Kwon'; Slug='dk-kwon'; Email='davidkwon0221@gmail.com'; RoleKo='회원'; RoleEn='Member'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); New=$true },
  @{ Name='김도균'; EnglishName='Do Gyun Kim'; Slug='do-gyun-kim'; Email='qscvf342@gmail.com'; RoleKo='회원'; RoleEn='Member'; New=$true },
  @{ Name='김상환'; EnglishName='Sanghwan Kim'; Slug='sanghwan-kim'; Email='kimsanghwan99@gmail.com'; RoleKo='회원'; RoleEn='Member' },
  @{ Name='김세린'; EnglishName='Serin Kim'; Slug='serin-kim'; Email='serene4260@gmail.com'; RoleKo='회원'; RoleEn='Member' },
  @{ Name='김시민'; EnglishName='Simin Kim'; Slug='simin-kim'; Email='rlatlawkd@gmail.com'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/kim-simin.webp'; EducationKo=@('연세대학교 응용통계학과 졸업','한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('B.S. in Applied Statistics, Yonsei University','M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); CareerKo=@('前 신한투자증권(現 신한금융투자)','삼성전자 AI·데이터분석 강사'); CareerEn=@('Former, Shinhan Investment Securities (now Shinhan Financial Investment)','AI and Data Analytics Instructor, Samsung Electronics'); New=$true },
  @{ Name='김유정'; EnglishName='Yoojung Kim'; Slug='yujeong-kim'; Email='liuting1004@gmail.com'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/kim-yujeong.webp'; LinkedIn='https://www.linkedin.com/in/yoojeng-kim'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','난징사범대학교 문학박사(중국어교육 전공)'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','Ph.D. in Chinese Language Education, Nanjing Normal University'); CareerKo=@('공립 고등학교 교사로 22년간 재직','인천중국어교과연구회 회장 역임(2년)','중등교사 임용시험 심층면접 평가위원 역임','세계시민·수업개선 선도교사 활동','중등 수업 지원단 및 교육정책 네트워크 교육현장 모니터단','한국어 강사 및 관광통역 안내원'); CareerEn=@('Public high school teacher for 22 years','Former President, Incheon Chinese Language Teachers Research Association (two years)','Former evaluator for in-depth interviews in the secondary teacher recruitment examination','Lead teacher for global citizenship and instructional improvement','Member, secondary education support group and education policy network field monitoring team','Korean-language instructor and licensed tour interpreter') },
  @{ Name='노성준'; EnglishName='Sungjun No'; Slug='seongjun-noh'; Email='noeeo111@gmail.com'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/no-sungjun.webp'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='류제우'; EnglishName='Jewoo Ryu'; Slug='jewoo-ryu'; Email='jw.orbit1@gmail.com'; RoleKo='회원'; RoleEn='Member'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='박민구'; EnglishName='Mingu Gordon Park'; Slug='mingu-park'; Email='mingupark1221@gmail.com'; RoleKo='연구원'; RoleEn='Researcher'; Image='/images/people/park-mingu.webp'; EducationKo=@('2026.03 ~ 현재 한양대학교 비트코인화폐철학과 석사과정 재학','2016.09 ~ 2023.02 고려대학교 KU-KIST융합대학원 이학박사(신경과학 전공)','2010.03 ~ 2016.08 고려대학교 바이오의공학부 공학사'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University (Mar. 2026–present)','Ph.D. in Neuroscience, KU-KIST Graduate School of Converging Science and Technology, Korea University (Sep. 2016–Feb. 2023)','B.Eng. in Biomedical Engineering, Korea University (Mar. 2010–Aug. 2016)'); CareerKo=@('2023.03 ~ 2025.09 기초과학연구원(IBS) 기억 및 교세포 연구단, 박사 후 연구원'); CareerEn=@('Postdoctoral Researcher, Memory and Glia Research Group, Institute for Basic Science (IBS) (Mar. 2023–Sep. 2025)') },
  @{ Name='박보영'; EnglishName='Boyoung Park'; Slug='boyoung-park'; Email='parkbo0@hanyang.ac.kr'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/park-boyoung.jpeg'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정','서강대학교 전자공학과 졸업'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University','B.S. in Electronic Engineering, Sogang University'); CareerKo=@('前 삼성전자 LCD 사업부(現 삼성디스플레이) 연구개발','前 LG전자 전략구매팀'); CareerEn=@('Former R&D, LCD Business, Samsung Electronics (now Samsung Display)','Former Strategic Procurement Team, LG Electronics') },
  @{ Name='박선협'; EnglishName='Seonhyeop Park'; Slug='seonhyeop-park'; Email='821psh@gmail.com'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/park-seonhyeop.webp' },
  @{ Name='박시우'; EnglishName='Siwoo Park'; Slug='siwoo-park'; Email='ciwoolove@gmail.com'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/park-siwoo.webp'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='선우훈'; EnglishName='Sunwoo Hoon'; Slug='sunwoo-hoon'; Email='youstudy2023@gmail.com'; RoleKo='회원'; RoleEn='Member'; New=$true },
  @{ Name='이정은'; EnglishName='Jungeun Lee'; Slug='jungeun-lee'; Email='emailkristinlee@gmail.com'; RoleKo='회원'; RoleEn='Member'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='이종범'; EnglishName='Lee Jong Beom'; Slug='lee-jong-beom'; Email='leeeejb@gmail.com'; RoleKo='회원'; RoleEn='Member'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University'); New=$true },
  @{ Name='조용래'; EnglishName='Yongrae Cho'; Slug='yongrae-cho'; Email='wolfwallet@hanyang.ac.kr'; RoleKo='회원'; RoleEn='Member'; EducationKo=@('한양대학교 비트코인화폐철학과 석사과정'); EducationEn=@('M.A. candidate, Department of Bitcoin Monetary Philosophy, Hanyang University') },
  @{ Name='조준호'; EnglishName='June Ho Cho'; Slug='june-ho-cho'; Email='mobickbear@gmail.com'; RoleKo='회원'; RoleEn='Member'; ReportParticleKo='가'; Image='/images/people/cho-june-ho.webp'; YouTube='https://www.youtube.com/@모빅베어'; EducationKo=@('서강대학교 화공생명공학과 석사과정'); EducationEn=@('M.S. candidate, Department of Chemical and Biomolecular Engineering, Sogang University'); New=$true },
  @{ Name='진승주'; EnglishName='Seungju Jin'; Slug='seungju-jin'; Email='gufudu1234@gmail.com'; RoleKo='회원'; RoleEn='Member'; Image='/images/people/jin-seungju.webp'; LinkedIn='https://www.linkedin.com/in/seungjoojin' },
  @{ Name='최덕현'; EnglishName='Choi Deok Hyun'; Slug='choi-deok-hyun'; Email='dhchoi1975@gmail.com'; RoleKo='회원'; RoleEn='Member'; New=$true },
  @{ Name='정두루'; EnglishName='Dooroo Chung'; Slug='dooroo-chung'; Email='doorooch@gmail.com'; RoleKo='운영 매니저'; RoleEn='Operations Manager'; Image='/images/people/jeong-duru.webp'; LinkedIn='https://www.linkedin.com/in/dooroo-chung/'; EducationKo=@('University of Southern California. B.S. Architectural Studies'); EducationEn=@('B.S. in Architectural Studies, University of Southern California'); CareerKo=@('(주)오태버스'); CareerEn=@('OtaVerse Co., Ltd.') },
  @{ Name='한상준'; EnglishName='Sangjun Han'; Slug='sangjun-han'; Email='75cinta@gmail.com'; RoleKo='영문 번역가'; RoleEn='English Translator'; Image='/images/people/han-sangjun.webp'; LinkedIn='https://www.linkedin.com/in/samuel-j-hahn-2a9149262/en'; YouTube='https://www.youtube.com/@SamuelJHahn_Mo'; EducationKo=@('한국외대 마인어과 학사'); EducationEn=@('B.A. in Malay-Indonesian Studies, Hankuk University of Foreign Studies') },
  @{ Name='윤성아'; EnglishName='Sungah Yoon'; Slug='sungah-yoon'; Email='seongah7865@gmail.com'; RoleKo='디자이너'; RoleEn='Designer'; Image='/images/people/yoon-sungah.jpeg'; LinkedIn='https://www.linkedin.com/in/seongahyoun'; EducationKo=@('서울대학교 미술대학 디자인학부 석사과정 재학','홍익대학교 미술대학 산업디자인학과 졸업'); EducationEn=@('M.A. candidate, Department of Design, College of Fine Arts, Seoul National University','B.F.A. in Industrial Design, College of Fine Arts, Hongik University') }
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

function NewProfilePage($Profile, [string]$Locale) {
  $isKo = $Locale -eq 'ko'
  $templateRelative = if ($isKo) { 'ko/people/sanghwan-kim.html' } else { 'people/sanghwan-kim.html' }
  $targetRelative = if ($isKo) { "ko/people/$($Profile.Slug).html" } else { "people/$($Profile.Slug).html" }
  $templatePath = Join-Path $ProjectRoot $templateRelative
  $targetPath = Join-Path $ProjectRoot $targetRelative
  $sourceName = if ($isKo) { '김상환' } else { 'Sanghwan Kim' }
  $targetName = if ($isKo) { $Profile.Name } else { $Profile.EnglishName }
  $html = [System.IO.File]::ReadAllText($templatePath)
  $html = $html.Replace('sanghwan-kim', $Profile.Slug)
  $html = $html.Replace($sourceName, $targetName)
  $html = $html.Replace('kimsanghwan99@gmail.com', $Profile.Email)
  [System.IO.File]::WriteAllText($targetPath, $html, [System.Text.UTF8Encoding]::new($false))
}

function PersonCard($Profile, [string]$Locale) {
  $isKo = $Locale -eq 'ko'
  $name = if ($isKo) { $Profile.Name } else { $Profile.EnglishName }
  $role = if ($isKo) { $Profile.RoleKo } else { $Profile.RoleEn }
  $prefix = if ($isKo) { '/ko' } else { '' }
  $label = if ($isKo) { '프로필' } else { 'Profile' }
  $photo = if ($Profile.Image) {
    '          <div class="person__photo"><img src="' + (Encode $Profile.Image) + '" alt="' + (Encode $name) + '" loading="lazy" decoding="async"></div>'
  } else {
    '          <div class="person__photo person__photo--empty" aria-hidden="true"></div>'
  }
  @"
        <article class="person">
$photo
          <h2 class="person__name">$(Encode $name)</h2>
          <p class="person__role">$(Encode $role)</p>
          <a class="person__profile" href="$prefix/people/$($Profile.Slug)">$label</a>
        </article>
"@
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
$actionsPattern = [regex]::new('<div class="profile__actions">.*?</div>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
$generatedPattern = [regex]::new('\s*<!-- PROFILE DETAILS FROM (?:METANOMIA\.XLSX|MEMBER ROSTER GOOGLE SHEET) -->.*?<!-- /PROFILE DETAILS FROM (?:METANOMIA\.XLSX|MEMBER ROSTER GOOGLE SHEET) -->', [System.Text.RegularExpressions.RegexOptions]::Singleline)
$updated = 0

foreach ($profile in $profiles) {
  foreach ($locale in @('ko', 'en')) {
    $relative = if ($locale -eq 'ko') { "ko/people/{0}.html" } else { "people/{0}.html" }
    $path = Join-Path $ProjectRoot ($relative -f $profile.Slug)
    if (-not (Test-Path -LiteralPath $path)) {
      if (-not $profile.New) { throw "Missing profile page: $path" }
      NewProfilePage $profile $locale
    }
    $html = [System.IO.File]::ReadAllText($path)
    $html = $generatedPattern.Replace($html, '')

    $displayName = if ($locale -eq 'ko') { $profile.Name } else { $profile.EnglishName }
    $displayRole = if ($locale -eq 'ko') { $profile.RoleKo } else { $profile.RoleEn }
    $html = [regex]::Replace($html, '<title>[^<]+ \| Metanomia</title>', '<title>' + (Encode $displayName) + ' | Metanomia</title>', 1)
    $html = [regex]::Replace($html, '<meta name="description" content="[^"]*" />', '<meta name="description" content="' + (Encode $displayName) + ' · ' + (Encode $displayRole) + '" />', 1)
    $html = [regex]::Replace($html, '<meta property="og:title" content="[^"]*" />', '<meta property="og:title" content="' + (Encode $displayName) + ' | Metanomia" />', 1)
    $html = [regex]::Replace($html, '<meta property="og:description" content="[^"]*" />', '<meta property="og:description" content="' + (Encode $displayName) + ' · ' + (Encode $displayRole) + '" />', 1)
    $html = [regex]::Replace($html, '<meta name="twitter:title" content="[^"]*" />', '<meta name="twitter:title" content="' + (Encode $displayName) + ' | Metanomia" />', 1)
    $html = [regex]::Replace($html, '<meta name="twitter:description" content="[^"]*" />', '<meta name="twitter:description" content="' + (Encode $displayName) + ' · ' + (Encode $displayRole) + '" />', 1)
    $html = [regex]::Replace($html, '<h1 class="profile__name">[^<]+</h1>', '<h1 class="profile__name">' + (Encode $displayName) + '</h1>', 1)
    $html = [regex]::Replace($html, '<p class="profile__role">[^<]+</p>', '<p class="profile__role">' + (Encode $displayRole) + '</p>', 1)
    if ($locale -eq 'ko') {
      $particle = if ($profile.ReportParticleKo) { $profile.ReportParticleKo } else { '이' }
      $html = [regex]::Replace($html, '<h2 class="profile__h">[^<]+(?:이|가) 쓴 보고서</h2>', '<h2 class="profile__h">' + (Encode $displayName) + $particle + ' 쓴 보고서</h2>', 1)
    } else {
      $html = [regex]::Replace($html, '<h2 class="profile__h">Reports by [^<]+</h2>', '<h2 class="profile__h">Reports by ' + (Encode $displayName) + '</h2>', 1)
    }

    if ($profile.Image) {
      $photo = '<div class="profile__photo"><img src="' + (Encode $profile.Image) + '" alt="' + (Encode $displayName) + '" loading="lazy" decoding="async"></div>'
      $html = [regex]::Replace($html, '<div class="profile__photo(?: profile__photo--empty)?"(?: aria-hidden="true")?>.*?</div>', $photo, 1, [System.TimeSpan]::FromSeconds(2))
      $absoluteImage = 'https://metanomia-site.vercel.app' + $profile.Image
      $html = [regex]::Replace($html, '<meta property="og:image" content="[^"]*" />', '<meta property="og:image" content="' + (Encode $absoluteImage) + '" />', 1)
      $html = [regex]::Replace($html, '<meta name="twitter:image" content="[^"]*" />', '<meta name="twitter:image" content="' + (Encode $absoluteImage) + '" />', 1)
    }

    $actions = @"
<div class="profile__actions">
            <a class="btn btn--ghost" href="mailto:$(Encode $profile.Email)">$(Encode $profile.Email)</a>
"@
    if ($profile.LinkedIn) {
      $actions += "`r`n            <a class=`"btn btn--ghost`" href=`"$(Encode $profile.LinkedIn)`" target=`"_blank`" rel=`"noopener noreferrer`">LinkedIn ↗</a>"
    }
    if ($profile.YouTube) {
      $actions += "`r`n            <a class=`"btn btn--ghost`" href=`"$(Encode $profile.YouTube)`" target=`"_blank`" rel=`"noopener noreferrer`">YouTube ↗</a>"
    }
    $actions += "`r`n          </div>"
    if (-not $actionsPattern.IsMatch($html)) { throw "Profile actions not found: $path" }
    $html = $actionsPattern.Replace($html, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $actions }, 1)

    $education = if ($locale -eq 'ko') { $profile.EducationKo } else { $profile.EducationEn }
    $career = if ($locale -eq 'ko') { $profile.CareerKo } else { $profile.CareerEn }
    $labels = if ($locale -eq 'ko') { @{ Education='학력'; Career='경력' } } else { @{ Education='Education'; Career='Career' } }

    $detailBlocks = @(
      (DetailBlock $labels.Education $education)
      (DetailBlock $labels.Career $career)
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $detailsBody = $detailBlocks -join "`r`n"

    if ($detailsBody) {
      $details = @"

          <!-- PROFILE DETAILS FROM MEMBER ROSTER GOOGLE SHEET -->
          <dl class="profile__details">
$detailsBody          </dl>
          <!-- /PROFILE DETAILS FROM MEMBER ROSTER GOOGLE SHEET -->
"@
      $html = $actionsPattern.Replace($html, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $m.Value + $details }, 1)
    }

    $html = [regex]::Replace($html, 'style\.css\?v=[^"'']+', 'style.css?v=20261009-member-roster')
    [System.IO.File]::WriteAllText($path, $html, $utf8)
    $updated++
  }
}

$taeminCards = @{
  ko = @"
        <article class="person" id="main-content">
          <div class="person__photo"><img src="/images/people/oh-taemin.webp" alt="오태민" loading="lazy" decoding="async"></div>
          <h2 class="person__name">오태민</h2>
          <p class="person__role">연구책임자</p>
          <a class="person__profile" href="/ko/people/taemin-oh">프로필</a>
        </article>
"@
  en = @"
        <article class="person" id="main-content">
          <div class="person__photo"><img src="/images/people/oh-taemin.webp" alt="Taemin Oh" loading="lazy" decoding="async"></div>
          <h2 class="person__name">Taemin Oh</h2>
          <p class="person__role">Research Lead</p>
          <a class="person__profile" href="/people/taemin-oh">Profile</a>
        </article>
"@
}
$gridPattern = [regex]::new('(<section class="people people--members">.*?<div class="people__grid">).*?(</div>\s*</div>\s*</section>)', [System.Text.RegularExpressions.RegexOptions]::Singleline)
foreach ($locale in @('ko', 'en')) {
  $membersRelative = if ($locale -eq 'ko') { 'ko/members.html' } else { 'members.html' }
  $membersPath = Join-Path $ProjectRoot $membersRelative
  $membersHtml = [System.IO.File]::ReadAllText($membersPath)
$cards = $taeminCards[$locale] + "`r`n" + (($profiles | ForEach-Object { PersonCard $_ $locale }) -join "`r`n") + "`r`n"
  if (-not $gridPattern.IsMatch($membersHtml)) { throw "Members grid not found: $membersPath" }
  $membersHtml = $gridPattern.Replace($membersHtml, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $m.Groups[1].Value + "`r`n" + $cards + '      ' + $m.Groups[2].Value }, 1)
  $membersHtml = [regex]::Replace($membersHtml, 'style\.css\?v=[^"'']+', 'style.css?v=20261009-member-roster')
  [System.IO.File]::WriteAllText($membersPath, $membersHtml, $utf8)
}

$sitemapPath = Join-Path $ProjectRoot 'sitemap.xml'
$sitemap = [System.IO.File]::ReadAllText($sitemapPath)
$sitemapMarker = '  <!-- GENERATED CRYPTO NEWS START -->'
$newSitemapEntries = ''
foreach ($profile in ($profiles | Where-Object { $_.New })) {
  $enUrl = "https://metanomia-site.vercel.app/people/$($profile.Slug)"
  $koUrl = "https://metanomia-site.vercel.app/ko/people/$($profile.Slug)"
  if ($sitemap.Contains("<loc>$enUrl</loc>")) { continue }
  foreach ($url in @($enUrl, $koUrl)) {
    $newSitemapEntries += @"
  <url>
    <loc>$url</loc>
    <lastmod>2026-10-09</lastmod>
    <priority>0.6</priority>
    <xhtml:link rel="alternate" hreflang="ko" href="$koUrl"/>
    <xhtml:link rel="alternate" hreflang="en" href="$enUrl"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="$enUrl"/>
  </url>

"@
  }
}
if ($newSitemapEntries) {
  if (-not $sitemap.Contains($sitemapMarker)) { throw 'Generated crypto news marker not found in sitemap.xml' }
  $sitemap = $sitemap.Replace($sitemapMarker, $newSitemapEntries + $sitemapMarker)
  [System.IO.File]::WriteAllText($sitemapPath, $sitemap, $utf8)
}

Write-Host "Updated $updated localized profile pages and both member indexes from the Google Sheet roster."
