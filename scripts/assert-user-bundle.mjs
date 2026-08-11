import { readFileSync, readdirSync } from 'node:fs';
import { extname, resolve } from 'node:path';

const output = process.argv[2]
  ? resolve(process.cwd(), process.argv[2])
  : resolve(import.meta.dirname, '..', 'apps', 'web', 'dist-user');
const forbidden = ['/v1/auth/admin-login', '/v1/admin/', '管理员控制台'];
const textExtensions = new Set(['.html', '.js', '.css', '.json', '.map']);

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

const files = filesUnder(output).filter((path) => textExtensions.has(extname(path)));
for (const marker of forbidden) {
  const found = files.find((path) => readFileSync(path, 'utf8').includes(marker));
  if (found) throw new Error(`User desktop bundle contains forbidden marker ${JSON.stringify(marker)} in ${found}`);
}
console.log(`User desktop bundle isolation passed (${files.length} files checked).`);
