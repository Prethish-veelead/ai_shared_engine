const fs = require('fs');

const transcriptPath = 'C:\\Users\\PrethishGA\\.gemini\\antigravity\\brain\\107217ad-11b2-4624-a7fe-25dff78f1d90\\.system_generated\\logs\\transcript_full.jsonl';
const lines = fs.readFileSync(transcriptPath, 'utf8').split('\n');

let latestCode = null;

for (const line of lines) {
  if (!line) continue;
  try {
    const obj = JSON.parse(line);
    if (obj.tool_calls) {
      for (const tc of obj.tool_calls) {
        if (tc.name === 'write_to_file' || tc.name === 'replace_file_content') {
           const targetFile = tc.args.TargetFile || '';
           if (targetFile.includes('bots') && targetFile.includes('page.tsx')) {
              console.log("=== Found write to bots/page.tsx at step " + obj.step_index);
              if (tc.args.CodeContent) {
                 latestCode = tc.args.CodeContent;
              } else if (tc.args.ReplacementContent) {
                 console.log("Found replacement: ", tc.args.ReplacementContent.substring(0, 100));
              }
           }
        }
      }
    }
  } catch (e) {}
}

if (latestCode) {
   fs.writeFileSync('C:\\Users\\PrethishGA\\Downloads\\ai-search-engine & admin portal\\admin-portal\\recovered_bots.tsx', latestCode);
   console.log("Wrote latest full code to recovered_bots.tsx!");
}
