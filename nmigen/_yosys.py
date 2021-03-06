import os
import sys
import re
import subprocess
try:
    from importlib import metadata as importlib_metadata # py3.8+ stdlib
except ImportError:
    try:
        import importlib_metadata # py3.7- shim
    except ImportError:
        importlib_metadata = None # not installed

from ._toolchain import has_tool, require_tool


__all__ = ["YosysError", "YosysBinary", "find_yosys"]


class YosysError(Exception):
    pass


class YosysBinary:
    @classmethod
    def available(cls):
        """Check for Yosys availability.

        Returns
        -------
        available : bool
            ``True`` if Yosys is installed, ``False`` otherwise. Installed binary may still not
            be runnable, or might be too old to be useful.
        """
        raise NotImplementedError

    @classmethod
    def version(cls):
        """Get Yosys version.

        Returns
        -------
        major : int
            Major version.
        minor : int
            Minor version.
        distance : int
            Distance to last tag per ``git describe``. May not be exact for system Yosys.
        """
        raise NotImplementedError

    @classmethod
    def run(cls, args, stdin=""):
        """Run Yosys process.

        Parameters
        ----------
        args : list of str
            Arguments, not including the program name.
        stdin : str
            Standard input.

        Returns
        -------
        stdout : str
            Standard output.

        Exceptions
        ----------
        YosysError
            Raised if Yosys returns a non-zero code. The exception message is the standard error
            output.
        """
        raise NotImplementedError


class _BuiltinYosys(YosysBinary):
    YOSYS_PACKAGE = "nmigen_yosys"

    @classmethod
    def available(cls):
        if importlib_metadata is None:
            return False
        try:
            importlib_metadata.version(cls.YOSYS_PACKAGE)
            return True
        except importlib_metadata.PackageNotFoundError:
            return False

    @classmethod
    def version(cls):
        version = importlib_metadata.version(cls.YOSYS_PACKAGE)
        match = re.match(r"^(\d+)\.(\d+)(?:\.post(\d+))?", version)
        return (int(match[1]), int(match[2]), int(match[3] or 0))

    @classmethod
    def run(cls, args, stdin=""):
        popen = subprocess.Popen([sys.executable, "-m", cls.YOSYS_PACKAGE, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8")
        stdout, stderr = popen.communicate(stdin)
        if popen.returncode:
            raise YosysError(stderr.strip())
        else:
            return stdout


class _SystemYosys(YosysBinary):
    YOSYS_BINARY = "yosys"

    @classmethod
    def available(cls):
        return has_tool(cls.YOSYS_BINARY)

    @classmethod
    def version(cls):
        version = cls.run(["-V"])
        match = re.match(r"^Yosys (\d+)\.(\d+)(?:\+(\d+))?", version)
        return (int(match[1]), int(match[2]), int(match[3] or 0))

    @classmethod
    def run(cls, args, stdin=""):
        popen = subprocess.Popen([require_tool(cls.YOSYS_BINARY), *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8")
        stdout, stderr = popen.communicate(stdin)
        # If Yosys is built with an evaluation version of Verific, then Verific license
        # information is printed first. It consists of empty lines and lines starting with `--`,
        # which are not normally a part of Yosys output, and can be fairly safely removed.
        #
        # This is not ideal, but Verific license conditions rule out any other solution.
        stdout = re.sub(r"\A(-- .+\n|\n)*", "", stdout)
        if popen.returncode:
            raise YosysError(stderr.strip())
        else:
            return stdout


def find_yosys(requirement):
    """Find an available Yosys executable of required version.

    Parameters
    ----------
    requirement : function
        Version check. Should return ``True`` if the version is acceptable, ``False`` otherwise.

    Returns
    -------
    yosys_binary : subclass of YosysBinary
        Proxy for running the requested version of Yosys.

    Exceptions
    ----------
    YosysError
        Raised if required Yosys version is not found.
    """
    proxies = []
    clauses = os.environ.get("NMIGEN_USE_YOSYS", "system,builtin").split(",")
    for clause in clauses:
        if clause == "builtin":
            proxies.append(_BuiltinYosys)
        elif clause == "system":
            proxies.append(_SystemYosys)
        else:
            raise YosysError("The NMIGEN_USE_YOSYS environment variable contains "
                             "an unrecognized clause {!r}"
                             .format(clause))
    for proxy in proxies:
        if proxy.available() and requirement(proxy.version()):
            return proxy
    else:
        if "NMIGEN_USE_YOSYS" in os.environ:
            raise YosysError("Could not find an acceptable Yosys binary. Searched: {}"
                             .format(", ".join(clauses)))
        else:
            raise YosysError("Could not find an acceptable Yosys binary. The `nmigen_yosys` PyPI "
                             "package, if available for this platform, can be used as fallback")
