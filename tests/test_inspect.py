"""Used-car scan on the cleared-codes virtual car, plus HTML escaping."""
import subprocess
import sys

from car_use.inspection_report import build, render_html, render_markdown


def test_cleared_codes_is_a_red_scan(sim):
    report = build(sim("cleared-codes"), expect_vin="1G1PE5SB7F7000999")
    assert report["verdict"] == "red"
    titles = " ".join(item["title"] for item in report["items"])
    assert "cleared" in titles.lower()
    red = next(item for item in report["items"] if item["level"] == "red")
    assert "11" in red["detail"]
    text = render_markdown(report)
    assert "Do not treat this car as clean" in text
    assert "## Red" in text


def test_matching_vin_on_a_healthy_car_has_no_red(sim):
    v = sim("healthy")
    report = build(v, expect_vin=v.vin)
    assert report["verdict"] != "red"
    assert any(item["level"] == "green" and "VIN matches" in item["title"] for item in report["items"])
    assert any("Odometer" in item["title"] for item in report["items"])


def test_html_escapes_text_and_the_cli_writes_it(tmp_path, sim):
    report = build(sim("cleared-codes"))
    report["items"][0]["detail"] = "<script>alert(1)</script>"
    page = render_html(report)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page

    out = tmp_path / "scan.html"
    proc = subprocess.run(
        [sys.executable, "-m", "car_use.run", "inspect", "--sim", "cleared-codes",
         "--html", str(out)],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Do not treat this car as clean" in proc.stdout
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
