#!/usr/bin/env python3
"""
Spike: Claude CLI subprocess 호출 테스트
- subprocess로 claude CLI 호출
- --output-format json 플래그 테스트
- JSON 파싱 가능 여부 확인
- 결과를 data/spike_claude_cli.json 에 저장
"""

import subprocess
import json
import sys
import os
import time

OUTPUT_PATH = "/home/jun99/claude/infoke/data/spike_claude_cli.json"
CLAUDE_CMD = "claude"

results = {
    "tests": [],
    "summary": {}
}


def run_test(label: str, args: list[str], prompt: str, parse_json: bool = False) -> dict:
    """단일 테스트 케이스를 실행하고 결과를 반환."""
    print(f"\n[TEST] {label}")
    cmd = [CLAUDE_CMD] + args + [prompt]
    print(f"  cmd: {' '.join(cmd)}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        elapsed = round(time.time() - start, 2)

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        returncode = result.returncode

        print(f"  returncode: {returncode}")
        print(f"  elapsed: {elapsed}s")
        print(f"  stdout (first 300 chars): {stdout[:300]}")
        if stderr:
            print(f"  stderr (first 200 chars): {stderr[:200]}")

        json_parsed = None
        json_parse_success = False
        json_parse_error = None
        json_parse_strategy = None

        if parse_json and stdout:
            import re
            # 전략 1: stdout 자체가 JSON (--output-format json 플래그 사용 시 envelope JSON)
            try:
                json_parsed = json.loads(stdout)
                json_parse_success = True
                json_parse_strategy = "direct_json"
                # envelope JSON인 경우 result 필드 내 실제 응답도 파싱 시도
                if isinstance(json_parsed, dict) and "result" in json_parsed:
                    result_str = json_parsed["result"].strip()
                    # result 안의 ```json ... ``` 블록 추출
                    inner_match = re.search(r"```json\s*([\s\S]*?)\s*```", result_str)
                    if inner_match:
                        try:
                            inner = json.loads(inner_match.group(1))
                            json_parsed["_result_parsed"] = inner
                            print(f"  envelope result parsed: {json.dumps(inner, ensure_ascii=False)[:200]}")
                        except json.JSONDecodeError:
                            pass
                    else:
                        try:
                            inner = json.loads(result_str)
                            json_parsed["_result_parsed"] = inner
                            print(f"  envelope result parsed (direct): {json.dumps(inner, ensure_ascii=False)[:200]}")
                        except json.JSONDecodeError:
                            pass
                print(f"  json_parsed (strategy={json_parse_strategy}): type={type(json_parsed).__name__}, keys={list(json_parsed.keys()) if isinstance(json_parsed, dict) else 'N/A'}")
            except json.JSONDecodeError as e:
                json_parse_error = str(e)
                # 전략 2: ```json ... ``` 코드 블록 추출
                match = re.search(r"```json\s*([\s\S]*?)\s*```", stdout)
                if match:
                    try:
                        json_parsed = json.loads(match.group(1))
                        json_parse_success = True
                        json_parse_error = None
                        json_parse_strategy = "code_block"
                        print(f"  json_parsed (strategy=code_block): {json.dumps(json_parsed, ensure_ascii=False)[:200]}")
                    except json.JSONDecodeError as e2:
                        json_parse_error = f"direct: {e}; code_block: {e2}"
                # 전략 3: 중괄호 블록 추출
                if not json_parse_success:
                    match2 = re.search(r"\{[\s\S]*\}", stdout)
                    if match2:
                        try:
                            json_parsed = json.loads(match2.group(0))
                            json_parse_success = True
                            json_parse_error = None
                            json_parse_strategy = "brace_extraction"
                            print(f"  json_parsed (strategy=brace_extraction): {json.dumps(json_parsed, ensure_ascii=False)[:200]}")
                        except json.JSONDecodeError as e3:
                            json_parse_error = f"direct: {e}; brace: {e3}"

        test_result = {
            "label": label,
            "cmd": cmd,
            "returncode": returncode,
            "elapsed_sec": elapsed,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
            "json_parse_attempted": parse_json,
            "json_parse_success": json_parse_success,
            "json_parse_error": json_parse_error,
            "json_parse_strategy": json_parse_strategy,
            "json_parsed": json_parsed,
        }
        return test_result

    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - start, 2)
        print(f"  TIMEOUT after {elapsed}s")
        return {
            "label": label,
            "cmd": cmd,
            "returncode": -1,
            "elapsed_sec": elapsed,
            "stdout": "",
            "stderr": "",
            "success": False,
            "error": "TimeoutExpired",
            "json_parse_attempted": parse_json,
            "json_parse_success": False,
            "json_parse_error": "TimeoutExpired",
            "json_parse_strategy": None,
            "json_parsed": None,
        }
    except FileNotFoundError:
        print(f"  ERROR: claude command not found")
        return {
            "label": label,
            "cmd": cmd,
            "returncode": -1,
            "elapsed_sec": 0,
            "stdout": "",
            "stderr": "",
            "success": False,
            "error": "FileNotFoundError: claude not in PATH",
            "json_parse_attempted": parse_json,
            "json_parse_success": False,
            "json_parse_error": None,
            "json_parse_strategy": None,
            "json_parsed": None,
        }


def main():
    print("=== Claude CLI Subprocess Spike ===")
    print(f"claude path: {subprocess.run(['which', 'claude'], capture_output=True, text=True).stdout.strip()}")

    # 테스트 1: 기본 -p 호출 (plain text 응답)
    t1 = run_test(
        label="basic_text",
        args=["-p"],
        prompt='다음 JSON 형식으로만 응답하세요: {"title": "테스트", "score": 8.5}',
        parse_json=True,
    )
    results["tests"].append(t1)

    # 테스트 2: --output-format json 플래그
    t2 = run_test(
        label="output_format_json",
        args=["-p", "--output-format", "json"],
        prompt='다음 JSON 형식으로만 응답하세요: {"title": "테스트", "score": 8.5}',
        parse_json=True,
    )
    results["tests"].append(t2)

    # 테스트 3: 간단한 영문 JSON 응답
    t3 = run_test(
        label="simple_english_json",
        args=["-p", "--output-format", "json"],
        prompt='Reply with only this JSON: {"status": "ok", "value": 42}',
        parse_json=True,
    )
    results["tests"].append(t3)

    # 요약
    total = len(results["tests"])
    successes = sum(1 for t in results["tests"] if t["success"])
    json_successes = sum(1 for t in results["tests"] if t.get("json_parse_success"))

    results["summary"] = {
        "total_tests": total,
        "cli_call_success": successes,
        "json_parse_success": json_successes,
        "overall_pass": successes > 0,
    }

    print("\n=== SUMMARY ===")
    print(f"CLI call success: {successes}/{total}")
    print(f"JSON parse success: {json_successes}/{total}")

    # 저장
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
