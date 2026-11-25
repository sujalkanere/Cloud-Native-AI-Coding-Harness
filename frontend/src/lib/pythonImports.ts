const PYTHON_STDLIB = new Set([
  "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio", "asyncore",
  "atexit", "audioop", "base64", "bdb", "binascii", "binhex", "bisect", "builtins",
  "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs",
  "codeop", "collections", "colorsys", "compileall", "concurrent", "configparser",
  "contextlib", "contextvars", "copy", "copyreg", "cprofile", "crypt", "csv",
  "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
  "dis", "distutils", "doctest", "email", "encodings", "ensurepip", "enum",
  "errno", "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
  "ftplib", "functools", "gc", "getopt", "getpass", "gettext", "glob", "graphlib",
  "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http", "imaplib", "imghdr",
  "imp", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "keyword",
  "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox", "mailcap",
  "marshal", "math", "mimetypes", "mmap", "modulefinder", "msilib", "msvcrt",
  "multiprocessing", "netrc", "nis", "nntplib", "numbers", "operator", "optparse",
  "os", "ossaudiodev", "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
  "platform", "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
  "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri",
  "random", "re", "readline", "reprlib", "resource", "rlcompleter", "runpy",
  "sched", "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal",
  "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "spwd", "sqlite3",
  "ssl", "stat", "statistics", "string", "stringprep", "struct", "subprocess",
  "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
  "telnetlib", "tempfile", "termios", "test", "textwrap", "threading", "time",
  "timeit", "tkinter", "token", "tokenize", "tomllib", "trace", "traceback",
  "tracemalloc", "tty", "turtle", "turtledemo", "types", "typing", "unicodedata",
  "unittest", "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
  "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
  "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo", "__future__", "pytest",
]);

const PYPI_ALIASES: Record<string, string> = {
  pil: "pillow",
  cv2: "opencv-python",
  sklearn: "scikit-learn",
  bs4: "beautifulsoup4",
  yaml: "pyyaml",
  dotenv: "python-dotenv",
  jwt: "pyjwt",
  crypto: "pycryptodome",
  dateutil: "python-dateutil",
  git: "gitpython",
  wx: "wxpython",
  serial: "pyserial",
};

/**
 * Extracts third-party PyPI package names from Python source code,
 * excluding standard library and local workspace modules.
 */
export function detectExternalPythonPackages(
  code: string,
  workspaceFiles: string[] = []
): string[] {
  if (!code) return [];

  const localModules = new Set(
    workspaceFiles
      .map((f) => f.split("/").pop() || f)
      .filter((f) => f.endsWith(".py"))
      .map((f) => f.slice(0, -3).toLowerCase())
  );

  const detected = new Set<string>();
  const lines = code.split(/\r?\n/);

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;

    // Match: import a, b as c
    const importMatch = line.match(/^import\s+(.+)$/);
    if (importMatch) {
      const parts = importMatch[1].split(",");
      for (const part of parts) {
        const mod = part.trim().split(/\s+as\s+/)[0].split(".")[0].trim();
        addIfExternal(mod, localModules, detected);
      }
      continue;
    }

    // Match: from pkg.sub import x (ignore relative imports starting with '.')
    const fromMatch = line.match(/^from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\s+/);
    if (fromMatch) {
      const mod = fromMatch[1].split(".")[0].trim();
      addIfExternal(mod, localModules, detected);
    }
  }

  return Array.from(detected);
}

function addIfExternal(
  mod: string,
  localModules: Set<string>,
  detected: Set<string>
): void {
  if (!mod || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(mod)) return;
  const lower = mod.toLowerCase();
  if (PYTHON_STDLIB.has(lower) || localModules.has(lower)) return;
  const pkgName = PYPI_ALIASES[lower] || mod;
  detected.add(pkgName);
}
