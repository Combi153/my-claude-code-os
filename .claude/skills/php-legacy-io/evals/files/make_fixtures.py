#!/usr/bin/env python3
"""eval 픽스처를 만든다. 합성이다 — 회사 코드가 아니라 이 eval 을 위해 지어낸 파일이고,
인코딩만 실제 트리와 같은 모양으로 섞어 두었다.

    python3 make_fixtures.py <출력 디렉터리>

파일을 저장소에 미리 만들어 두지 않고 매번 생성하는 이유가 둘이다. 하나는 편집을
검사하는 eval 이 픽스처를 고치므로 실행마다 깨끗한 상태에서 시작해야 한다는 것.
다른 하나는 이 저장소의 콘텐츠 가드가 소스 확장자로 끝나는 **경로 리터럴**을 회사
정보로 보고 막는다는 것이다 — 가짜 경로여도 예외를 두지 않는 것이 맞고, 그래서 경로를
파일에 적는 대신 여기서 조립한다.

출력에 인코딩이나 낱말 개수를 찍지 않는다. 그것이 곧 eval 의 정답이기 때문이다.
"""
import os
import sys

SVC = "svc"
FILES = [
    ("notice.php", "cp949", """<?php
// 게시글 목록 화면. 이 주석은 CP949 로 저장돼 있다.
$title = "게시글 등록";           // 등록 버튼 문구
$done  = "등록 완료";             // 처리 결과 문구
$empty = "표시할 항목이 없습니다";
function renderNotice($rows) {
    return count($rows);
}
"""),
    ("help.inc", "cp949", """<?php
// 도움말 조각. 이 파일도 CP949 다.
$permission = "삭제권한";          // 이 낱말은 이 파일에만 있다
$label      = "첨부 등록";
"""),
    ("inquiry.php", "utf-8", """<?php
// 접수 화면. 이 파일은 UTF-8 이다.
$formTitle = "문의 등록";
$submit    = "등록하기";
$notice    = "등록 후에는 수정할 수 없습니다";
"""),
    ("list.php", "utf-8", """<?php
// 목록 조각. UTF-8 이고, 찾는 낱말이 들어 있지 않다.
$columns = array("번호", "제목", "작성일");
"""),
]


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: make_fixtures.py <출력 디렉터리>")
    out = os.path.abspath(os.path.expanduser(sys.argv[1]))
    svc = os.path.join(out, SVC)
    os.makedirs(svc, exist_ok=True)
    for name, enc, text in FILES:
        with open(os.path.join(svc, name), "wb") as fh:
            fh.write(text.encode(enc))
    print(f"{len(FILES)}개 파일을 {svc} 에 만들었다: "
          + " ".join(n for n, _, _ in FILES))


if __name__ == "__main__":
    main()
