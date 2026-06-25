// Electron 바이너리 무결성 보장 (Node 26 + electron 33 의 extract-zip 무음 실패 우회).
// electron 의 postinstall 이 dist 를 불완전하게 풀거나(프레임워크 누락) path.txt 를 안 쓰면,
// 캐시(또는 새 다운로드)된 zip 을 시스템 unzip 으로 직접 풀어 복구한다. 정상이면 즉시 통과.
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

const electronDir = path.dirname(require.resolve('electron/package.json'));
const { version } = require(path.join(electronDir, 'package.json'));

function platformPath() {
  switch (process.platform) {
    case 'mas':
    case 'darwin': return 'Electron.app/Contents/MacOS/Electron';
    case 'win32': return 'electron.exe';
    default: return 'electron';
  }
}
const pp = platformPath();
const distDir = path.join(electronDir, 'dist');

function looksInstalled() {
  if (!fs.existsSync(path.join(distDir, pp))) return false;
  if (process.platform === 'darwin' || process.platform === 'mas') {
    const fw = path.join(distDir, 'Electron.app/Contents/Frameworks/Electron Framework.framework/Electron Framework');
    if (!fs.existsSync(fw)) return false; // 프레임워크 누락 = 불완전 추출
  }
  return fs.existsSync(path.join(electronDir, 'path.txt'));
}

if (looksInstalled()) {
  console.log('[ensure-electron] OK — electron ' + version);
  process.exit(0);
}

console.log('[ensure-electron] dist 불완전 → 수동 추출 (Node ' + process.version + ' extract-zip 우회)');

(async () => {
  const { downloadArtifact } = require('@electron/get');
  let zipPath;
  try {
    zipPath = await downloadArtifact({
      version,
      artifactName: 'electron',
      platform: process.env.npm_config_platform || process.platform,
      arch: process.env.npm_config_arch || process.arch,
      checksums: require(path.join(electronDir, 'checksums.json')),
    });
  } catch (e) {
    console.error('[ensure-electron] 다운로드 실패:', e.message);
    process.exit(1);
  }

  fs.rmSync(distDir, { recursive: true, force: true });
  fs.mkdirSync(distDir, { recursive: true });

  try {
    if (process.platform === 'win32') {
      cp.execSync(
        `powershell -NoProfile -Command "Expand-Archive -LiteralPath '${zipPath}' -DestinationPath '${distDir}' -Force"`,
        { stdio: 'inherit' });
    } else {
      cp.execSync(`unzip -q -o "${zipPath}" -d "${distDir}"`, { stdio: 'inherit' });
    }
  } catch (e) {
    console.error('[ensure-electron] 압축 해제 실패:', e.message);
    process.exit(1);
  }

  const dts = path.join(distDir, 'electron.d.ts');
  if (fs.existsSync(dts)) fs.renameSync(dts, path.join(electronDir, 'electron.d.ts'));
  fs.writeFileSync(path.join(electronDir, 'path.txt'), pp);

  console.log(looksInstalled()
    ? '[ensure-electron] 복구 완료 → ' + distDir
    : '[ensure-electron] 추출했지만 검증 실패 — 수동 확인 필요');
})();
