# after github sync main branch
절차

  1. origin의 최신 상태 가져오기

  git fetch origin
  GitHub에서 싱크한 origin/main 정보가 로컬로 내려옵니다.

  2. 로컬 main 업데이트

  git checkout main
  git pull origin main

  3. develop에 최신 main 반영

  git checkout develop

  여기서 두 가지 방법 중 선택:

  - rebase (커밋 히스토리를 깔끔하게 유지):
  git rebase main
  - merge (안전하고 히스토리 보존):
  git merge main

  커스텀 커밋이 2개뿐이라 rebase가 깔끔합니다. 다만 충돌이 발생하면 하나씩 해결해야 합니다.

  4. 충돌이 있다면

  - 충돌 파일 수정 후 git add <파일> → git rebase --continue
  - 너무 복잡하면 git rebase --abort로 되돌린 후 merge 방식으로 전환

  5. (선택) origin에 push

  git push origin develop --force-with-lease
  rebase를 했으면 --force-with-lease가 필요하고, merge를 했으면 일반 git push로 충분합니다.
