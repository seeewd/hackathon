아래처럼 Gemini가 응답하면 스크립트가 코드 블록을 추출해서 실행:

```python
node("curve_src", "Curve", 120, 120, nickname="source_curve")
node("ac_wall", "Archicad.Wall", 360, 120, nickname="wall")
wire("curve_src", 0, "ac_wall", 0)
```

