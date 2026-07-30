ABADDON 공식 홈페이지 업로드 방법

1. config.js를 메모장으로 엽니다.
2. YOUR_APPLICATION_ID를 Discord Developer Portal의 Application ID로 바꿉니다.
3. YOUR_INVITE_CODE를 공식 Discord 서버 초대 코드로 바꿉니다.
4. 이 폴더 안의 파일과 assets 폴더를 모두 GitHub 저장소 최상위에 업로드합니다.
5. GitHub → Settings → Pages에서
   Source: Deploy from a branch
   Branch: main
   Folder: /(root)
   로 설정합니다.

기존 abaddon-policy 저장소에 그대로 덮어써도 됩니다.
정책 URL은 계속 아래 주소를 사용할 수 있습니다.
- /terms.html
- /privacy.html

중요:
- ZIP 파일 자체를 GitHub에 올리지 말고 압축을 푼 내용물을 올리세요.
- 봇 초대 권한 값(permissions)은 필요한 권한에 맞게 Discord OAuth2 URL Generator에서 다시 만들 수 있습니다.
