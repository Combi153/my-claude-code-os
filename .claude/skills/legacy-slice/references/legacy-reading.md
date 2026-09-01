# 레거시 트리를 읽는 법

This tree is not one encoding. Roughly half of it is EUC-KR, and the split does not
follow directories — two files in the same service differ. Every tool you have behaves
differently on those files, and **three of them fail silently**.

Read this before your first search. A wrong answer here does not announce itself; it
arrives as an empty result, which reads exactly like "the rule is not there."

## 실측한 도구 행렬

Measured on a 489-line EUC-KR DAO containing `function` 9 times and `도움말` 3 times.
No NUL bytes — the file is text, only undecodable as UTF-8.

| 방법 | ASCII 검색 | 한글 검색 | 한글 표시 |
|---|---|---|---|
| Bash `grep` | **침묵, exit 1** | **침묵, exit 1** | — |
| Bash `grep -a` | 9 ✓ | 0, exit 1 | 깨짐 |
| Bash `rg` | 9 ✓ | **침묵, exit 1** | 깨짐 |
| Bash `rg --encoding euc-kr` | 9 ✓ | **3 ✓** | **정상 ✓** |
| **Grep 도구** | ✓ (rg 엔진) | 플래그를 못 주므로 위 `rg` 와 같다 | 깨짐 |
| **Read 도구** | — | — | **깨짐** |
| Bash `iconv -f EUC-KR -t UTF-8` | ✓ | ✓ | **정상 ✓** |

Two things to take from the table:

**BSD grep suppresses output entirely** on a file it judges binary — it does not print a
count, does not warn, and exits 1. `grep -c` printing nothing at all is the tell.

**Only `--encoding euc-kr` or `iconv` gets Korean right.** Everything else returns a
confident zero. Korean matters because in this codebase the business intent is written in
Korean comments — `// 서비스도움말 상세내용등록` is the sentence that tells you what a
method is for, and it is invisible to five of the seven rows above.

## 규칙

1. **인코딩을 먼저 확인한다.** `file -b --mime-encoding <path>` on every file you open.
   `iso-8859-1` here means EUC-KR (`file` guesses Latin-1 from the high bytes; the bytes
   are EUC-KR/CP949). Record it — the ledger has a 파일 인코딩 절 for this.

2. **레거시 트리에서 맨 `grep` 을 쓰지 않는다.** Use the Grep tool for ASCII patterns
   (its ripgrep engine reads these files), or `rg` in Bash. If you must use `grep`, use
   `grep -a`.

3. **한글로 검색할 때는 인코딩을 지정한다.** `rg --encoding euc-kr '패턴' <path>`.
   Without it you get zero matches on a file that contains the term.

4. **EUC-KR 파일의 한글을 읽을 때는 iconv 를 통과시킨다.**
   `iconv -f EUC-KR -t UTF-8 <path>` — pipe it to `sed -n 'A,Bp'` for a range. The Read
   tool renders the Korean as replacement characters, so a comment you read that way is
   not evidence of anything.

5. **빈 결과를 근거로 쓰지 않는다.** When you report that something is absent, name the
   command and the file's encoding alongside the claim. "grep found nothing" is not a
   finding until it is "`rg --encoding euc-kr` over these N files, all UTF-8, found
   nothing." An unqualified absence claim will be treated as unverified.

6. **읽기만 하는 동안에도 인코딩을 보존한다.** Never round-trip a legacy file through
   iconv back onto disk. Convert on the way to your eyes, never on the way to the file.
   A separate hook blocks edits that change encoding; that hook does not cover a careless
   `iconv -o`.

## 왜 이게 원장의 문제인가

The L0 loop's exit condition is that the red team comes back empty twice. If the
emptiness comes from tool blindness rather than from a complete ledger, the loop closes
having verified nothing — and every later phase joins on that ledger. This is the one
failure in the pipeline that gets *more* confident the more it is repeated, which is why
it is a documented rule rather than something each agent rediscovers.

`php-encoding-guard.py` already guards the **write** side. This file is the **read**
side. Encoding does not only bite when you edit.
