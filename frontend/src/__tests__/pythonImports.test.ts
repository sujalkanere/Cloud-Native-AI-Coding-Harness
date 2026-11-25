import { describe, it, expect } from "vitest";
import { detectExternalPythonPackages } from "../lib/pythonImports";

describe("detectExternalPythonPackages", () => {
  it("excludes Python standard library and local workspace modules", () => {
    const code = `
import os
import sys
from pathlib import Path
import json
import utils
from helpers import format_output
`;
    expect(detectExternalPythonPackages(code, ["main.py", "utils.py", "helpers.py"])).toEqual([]);
  });

  it("detects third-party imports and maps common PyPI aliases", () => {
    const code = `
import requests
import numpy as np
from PIL import Image
from bs4 import BeautifulSoup
import yaml
`;
    expect(detectExternalPythonPackages(code, ["app.py"])).toEqual([
      "requests",
      "numpy",
      "pillow",
      "beautifulsoup4",
      "pyyaml",
    ]);
  });

  it("ignores commented lines and relative imports", () => {
    const code = `
# import pandas
from .local_mod import helper
import flask
`;
    expect(detectExternalPythonPackages(code, [])).toEqual(["flask"]);
  });
});
