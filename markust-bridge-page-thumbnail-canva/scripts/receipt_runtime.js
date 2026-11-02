// Load once with exec_command, then new Function(source + '; return saveReceipt;')().
// The caller invokes Canva; this bridge only persists and summarizes its response.
async function saveReceipt({tools, result, request, baseline, baselinePath, jobDir, receiptId, skillDir, python = 'python3'}) {
  if (!/^[A-Za-z0-9_-]+$/.test(receiptId)) throw new Error('Use a unique simple receiptId.');
  const quote = value => "'" + String(value).replace(/'/g, "'\\''") + "'";
  const base = `${jobDir}/runtime/${receiptId}`;
  const paths = {raw: base + '-raw.json', summary: base + '-summary.json'};
  if (request) paths.request = base + '-request.json';
  if (baseline && baselinePath) throw new Error('Supply baseline or baselinePath, not both.');
  if (baseline || baselinePath) paths.baseline = baselinePath || base + '-baseline.json';
  const records = [[paths.raw, result]];
  if (request) records.push([paths.request, request]);
  if (baseline) records.push([paths.baseline, baseline]);
  // Chunked safely quoted argv; never interpolate JSON as shell syntax or print it.
  const writer = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); f=p.open(sys.argv[2],encoding='utf-8'); p.chmod(0o600); f.write(sys.argv[3]); f.close()";
  for (const [path, data] of records) {
    const serialized = JSON.stringify(data);
    for (let pos = 0; pos < serialized.length;) {
      let end = Math.min(pos + 12000, serialized.length);
      if (end < serialized.length && /[\uD800-\uDBFF]/.test(serialized[end - 1])) end--;
      const cmd = [python, '-c', writer, path, pos === 0 ? 'x' : 'a', serialized.slice(pos, end)].map(quote).join(' ');
      const saved = await tools.exec_command({cmd, max_output_tokens: 500});
      if (saved.exit_code !== 0) throw new Error('Receipt persistence failed; inspect the local file before retrying with a new receiptId.');
      pos = end;
    }
  }
  const args = [python, `${skillDir}/scripts/canva_adapter.py`, 'compact', '--receipt', paths.raw, '--out', paths.summary];
  if (request) args.push('--request', paths.request);
  if (paths.baseline) args.push('--baseline', paths.baseline);
  const summarized = await tools.exec_command({cmd: args.map(quote).join(' '), max_output_tokens: 6000});
  if (summarized.exit_code === undefined) throw new Error('Summary is still running; complete the command before proceeding.');
  try { return {paths, exitCode: summarized.exit_code, summary: JSON.parse(summarized.output)}; }
  catch { return {paths, exitCode: summarized.exit_code, inspectionRequired: 'Summary unavailable/truncated; inspect saved diagnostics before continuing.'}; }
}
