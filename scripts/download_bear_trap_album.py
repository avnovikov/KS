#!/usr/bin/env python3
"""Download full-resolution images from a Google Photos shared album."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# batch3 album: https://photos.app.goo.gl/3vU9naPvTLaNgkPq5
BATCH3_PHOTO_PAGES = [
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipPmBWpu5BrUld-yJwuJ2m9THd0bdvIES5OQLFsA?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipMPscUXU1qAkK5_1Cf_1-xW__LKnlkle7AWnI4E?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipOgdQOUCx7I9P3J51hqAwBtbPOGc14v3Pnf3ccm?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipNHNsumn5xzuyHH21L8xmB0a9MSKOwBU_5IQ5Nu?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipN7aCxdTc2r75eUbb-6LkK_6cpP0wsSawFudZLJ?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipMG5fjJ7vLf-EDRgaySehokVCVGgK-sivQW_cRJ?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipMyCpwx6RgM7I51kf8WRyE9Y3xJw7MFaSj9otI1?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipNF9zY_uAvKfocNqlbndniAhIuJzN3gyPrt05Tb?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipNm0YIgP8nAlkSLhPzo_PEP02ft8Ci8w7W8p75o?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipO_UM_6_fX5T1Or0yur_aaG_JUMHzarliH4k3lP?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipOlEumdRAPAKItHGgcXZG7qyt8wLkM1HNzwktxv?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
    "https://photos.google.com/share/AF1QipNEFzVegampy66bJWfjwmA0maNS7kw5Btbvzc3gOQZx9oPfGYNdapjbFMyRIxmv5g/photo/AF1QipOqjRF5BlfTWD0JkjQidaiIYECpw0dnlGLKrM04?key=UmlQOHE3OEg5SXBpVWh4a2NxLWUyTWhjSElIVS1R",
]


def curl_text(url: str) -> str:
    return subprocess.check_output(
        ["curl", "-sL", "-A", "Mozilla/5.0", url],
        text=True,
        errors="ignore",
    )


def curl_bytes(url: str, dest: Path) -> None:
    subprocess.check_call(["curl", "-sL", "-A", "Mozilla/5.0", "-o", str(dest), url])


def best_original_url(page_html: str) -> str:
    imgs = re.findall(r"https://lh3\.googleusercontent\.com/pw/[^\"\\]+", page_html)
    if not imgs:
        raise ValueError("no googleusercontent URL in page")
    bases = [u.split("=")[0] for u in imgs]
    # Longest token usually the full-res asset id
    base = max(set(bases), key=len)
    return base + "=d"


def download_batch3(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    import cv2

    for i, page in enumerate(BATCH3_PHOTO_PAGES, 1):
        html = curl_text(page)
        img_url = best_original_url(html)
        out = out_dir / f"b3-{i:02d}.png"
        curl_bytes(img_url, out)
        im = cv2.imread(str(out))
        assert im is not None, out
        h, w = im.shape[:2]
        print(f"wrote {out.name}: {w}x{h} ({out.stat().st_size // 1024} KB)  url={img_url[-20:]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "assets/reference/bear-trap/blockers-shots/batch3",
    )
    args = parser.parse_args()
    download_batch3(args.out)


if __name__ == "__main__":
    main()
