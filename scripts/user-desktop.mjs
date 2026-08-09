import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import process from 'node:process';

const workspace = resolve(import.meta.dirname, '..');
const desktopDir = resolve(workspace, 'apps', 'user-desktop');
const profile = JSON.parse(readFileSync(resolve(desktopDir, 'user-profile.json'), 'utf8'));
const desktopPackage = JSON.parse(readFileSync(resolve(desktopDir, 'package.json'), 'utf8'));
const command = process.argv[2] || 'dev';
const apiUrl = new URL(profile.apiUrl);
if (!['http:', 'https:'].includes(apiUrl.protocol) || apiUrl.username || apiUrl.password || apiUrl.search || apiUrl.hash) {
  throw new Error('user-profile.json apiUrl must be an http(s) origin without credentials, query, or hash');
}
const baseUrl = apiUrl.toString().replace(/\/$/, '');
const httpPermission = {
  identifier: 'http:default',
  allow: [{ url: `${baseUrl}/**` }],
};
const capability = (identifier, windows, permissions) => ({ identifier, windows, permissions });
const override = JSON.stringify({
  app: {
    security: {
      capabilities: [
        capability('user-main', ['main'], [
          'core:default', 'allow-open-print-window', httpPermission,
          'dialog:allow-save', 'fs:allow-write-file', 'log:default',
          {
            identifier: 'opener:allow-open-url',
            allow: [{ url: 'http://*' }, { url: 'https://*' }],
          },
        ]),
        capability('user-print', ['print'], ['core:default', httpPermission, 'log:default']),
      ],
    },
  },
});
const generatedConfigDirectory = mkdtempSync(join(tmpdir(), 'nerva-user-desktop-'));
const generatedConfig = join(generatedConfigDirectory, 'tauri.generated.json');
writeFileSync(generatedConfig, override, 'utf8');
process.on('exit', () => rmSync(generatedConfigDirectory, { recursive: true, force: true }));
const env = {
  ...process.env,
  CI: process.env.CI || 'true',
  VITE_API_URL: baseUrl,
  VITE_CLIENT_TYPE: 'user-desktop',
  VITE_APP_VERSION: desktopPackage.version,
  VITE_APP_ENV: command === 'dev' ? 'development' : 'local',
};

function newestDirectory(path, predicate = () => true) {
  if (!existsSync(path)) return undefined;
  return readdirSync(path, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && predicate(entry.name))
    .map((entry) => entry.name)
    .sort((left, right) => right.localeCompare(left, undefined, { numeric: true }))[0];
}

function configureWindowsToolchain() {
  if (process.platform !== 'win32') return;
  const programFilesX86 = process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)';
  const vsRoot = join(programFilesX86, 'Microsoft Visual Studio', '2022', 'BuildTools');
  const msvcRoot = join(vsRoot, 'VC', 'Tools', 'MSVC');
  const msvcVersion = newestDirectory(msvcRoot);
  const sdkRoot = join(programFilesX86, 'Windows Kits', '10');
  const sdkVersion = newestDirectory(join(sdkRoot, 'Lib'), (name) => existsSync(join(sdkRoot, 'Lib', name, 'um', 'x64')));
  if (!msvcVersion || !sdkVersion) return;
  const msvc = join(msvcRoot, msvcVersion);
  const cargoBin = process.env.USERPROFILE ? join(process.env.USERPROFILE, '.cargo', 'bin') : '';
  const pathKey = Object.keys(env).find((key) => key.toLowerCase() === 'path') || 'Path';
  env[pathKey] = [cargoBin, join(msvc, 'bin', 'Hostx64', 'x64'), join(sdkRoot, 'bin', sdkVersion, 'x64'), env[pathKey]]
    .filter(Boolean).join(';');
  env.LIB = [join(msvc, 'lib', 'x64'), join(sdkRoot, 'Lib', sdkVersion, 'ucrt', 'x64'), join(sdkRoot, 'Lib', sdkVersion, 'um', 'x64')].join(';');
  env.INCLUDE = [join(msvc, 'include'), join(sdkRoot, 'Include', sdkVersion, 'ucrt'), join(sdkRoot, 'Include', sdkVersion, 'shared'), join(sdkRoot, 'Include', sdkVersion, 'um'), join(sdkRoot, 'Include', sdkVersion, 'winrt')].join(';');
}

configureWindowsToolchain();
const cargo = process.platform === 'win32' && process.env.USERPROFILE
  ? join(process.env.USERPROFILE, '.cargo', 'bin', 'cargo.exe')
  : 'cargo';

function run(program, args, cwd = workspace, shell = false) {
  const result = spawnSync(program, args, { cwd, env, stdio: 'inherit', shell });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function runPnpm(args, cwd = workspace) {
  run(process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm', args, cwd, process.platform === 'win32');
}

if (command === 'dev') {
  runPnpm(['tauri', 'dev', '--config', generatedConfig], desktopDir);
} else if (command === 'frontend') {
  runPnpm(['--dir', resolve(workspace, 'apps', 'web'), 'build:user']);
} else if (command === 'build') {
  runPnpm(['tauri', 'build', '--bundles', 'nsis', '--target', 'x86_64-pc-windows-msvc', '--config', generatedConfig], desktopDir);
} else if (command === 'check') {
  run(cargo, ['fmt', '--manifest-path', resolve(desktopDir, 'src-tauri', 'Cargo.toml'), '--check']);
  run(cargo, ['test', '--manifest-path', resolve(desktopDir, 'src-tauri', 'Cargo.toml')]);
  run(cargo, ['clippy', '--manifest-path', resolve(desktopDir, 'src-tauri', 'Cargo.toml'), '--', '-D', 'warnings']);
} else {
  throw new Error(`unknown user desktop command: ${command}`);
}
