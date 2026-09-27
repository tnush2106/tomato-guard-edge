const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const dashboardPath = path.join(__dirname, '..', 'templates', 'TomatoGuard_Pro_Dashboard.html');
const html = fs.readFileSync(dashboardPath, 'utf8');
const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1]);

assert.ok(inlineScripts.length > 0, 'dashboard must contain executable inline JavaScript');
for (const script of inlineScripts) new Function(script);

assert.doesNotMatch(html, /\bMOCK_DATA\b|Math\.random\s*\(/, 'dashboard must not fabricate telemetry');
assert.match(html, /src="\/video\?overlay=0"/, 'dashboard must request the clean camera stream');
assert.match(html, /requestJson\([^)]*'\/api\/detections'/, 'dashboard must poll the live API');
assert.match(html, /sendHatCommand\('\/api\/relay'/, 'relay controls must call the HAT API');
assert.match(html, /sendHatCommand\('\/api\/hat\/mode'/, 'mode controls must call the HAT API');
assert.match(html, /sendHatCommand\('\/api\/hat\/action'/, 'HAT actions must call the HAT API');
assert.match(
  html,
  /hatState\.outputs_uncertain\s*!==\s*true/,
  'controls must remain locked while the relay state is uncertain',
);
for (const label of [
  'Late_Blight', 'Leaf_Miner', 'Magnesium_Deficiency',
  'Nitrogen_Deficiency', 'Potassium_Deficiency', 'Spotted_Wilt_Virus',
]) {
  assert.match(html, new RegExp(`\\b${label}\\s*:`), `dashboard must describe ${label}`);
}
assert.doesNotMatch(html, /\b(?:Early_Blight|Healthy)\s*:/, 'dashboard must match the six-class model');

console.log('dashboard static checks passed');
