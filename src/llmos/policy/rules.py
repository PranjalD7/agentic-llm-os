"""
Policy rule definitions.
Each entry is (regex_pattern, human_readable_reason).
Evaluated top-to-bottom; first match wins within each category.
BLOCKED is checked before RISKY.
"""
from typing import List, Tuple

RuleList = List[Tuple[str, str]]

BLOCKED_PATTERNS: RuleList = [
    # Disk wipe / format
    (r"\bdd\s+if=",                     "dd if= can overwrite or wipe disk devices"),
    (r"\bmkfs\.",                        "mkfs can format disk partitions"),
    (r"\b(fdisk|gdisk|parted)\b",        "Disk partitioning tools are blocked"),

    # Filesystem root destruction
    (r"rm\s+(-\w+\s+)*/?(\s+|$)",       "Deleting the filesystem root is blocked"),
    (r"rm\s+.*\s*/etc/(passwd|shadow|sudoers)", "Deleting system auth files is blocked"),
    (r"chmod\s+777\s+/\s*$",            "chmod 777 on the root filesystem is blocked"),

    # Fork bombs and resource exhaustion
    (r":\(\)\s*\{",                     "Fork bomb pattern detected"),
    (r":\(\)\s*\{\s*:\|",              "Fork bomb pattern detected"),

    # Privilege escalation
    (r"\bsudo\s+su\b",                  "sudo su escalation is blocked"),
    (r"\bpasswd\s+root\b",              "Changing the root password is blocked"),

    # Pipe to shell (arbitrary remote code execution)
    (r"curl\b.*\|\s*(ba|z|da)?sh",      "Piping curl output to a shell is blocked"),
    (r"wget\b.*\|\s*(ba|z|da)?sh",      "Piping wget output to a shell is blocked"),
    (r"fetch\b.*\|\s*(ba|z|da)?sh",     "Piping fetch output to a shell is blocked"),

    # Netcat listeners / reverse shells
    (r"\bnc\b.*-[le]",                  "Netcat listener/exec mode is blocked"),
    (r"\bncat\b.*-[le]",                "Ncat listener/exec mode is blocked"),

    # Python/perl/ruby socket reverse shell patterns
    (r"python\S*\s+-c\s+.*socket.*connect", "Raw socket reverse shell is blocked"),
    (r"perl\s+-e\s+.*socket",           "Perl socket reverse shell is blocked"),
]

RISKY_PATTERNS: RuleList = [
    # Package installation (can run arbitrary code)
    (r"\bpip\s+install\b",              "pip install can download and execute arbitrary code"),
    (r"\bnpm\s+install\b",              "npm install can run pre/post-install hooks"),
    (r"\bbrew\s+install\b",             "brew install downloads software from the internet"),
    (r"\bapt(-get)?\s+install\b",       "apt install modifies system packages"),
    (r"\bconda\s+install\b",            "conda install downloads software"),
    (r"\byarn\s+add\b",                 "yarn add can run install hooks"),

    # File deletion
    (r"\brm\s+-\w*r\w*\b",             "rm -r recursively deletes files"),
    (r"\brmdir\b",                      "rmdir removes directories"),
    (r"\bshred\b",                      "shred securely deletes files (unrecoverable)"),

    # Network access
    (r"\bcurl\b",                       "curl makes network requests"),
    (r"\bwget\b",                       "wget downloads files from the internet"),
    (r"\bssh\b",                        "ssh opens a remote shell connection"),
    (r"\bscp\b",                        "scp transfers files over the network"),
    (r"\brsync\b",                      "rsync can synchronize files over the network"),

    # Destructive git operations
    (r"\bgit\s+push\b",                 "git push modifies a remote repository"),
    (r"\bgit\s+reset\b",                "git reset can discard commits"),
    (r"\bgit\s+rebase\b",               "git rebase rewrites commit history"),
    (r"\bgit\s+force\b",                "git force operations can destroy history"),

    # Process / service control
    (r"\bkill\b",                       "kill terminates processes"),
    (r"\bpkill\b",                      "pkill terminates processes by name"),
    (r"\bkillall\b",                    "killall terminates all matching processes"),
    (r"\bsystemctl\b",                  "systemctl controls system services"),
    (r"\blaunchctl\b",                  "launchctl controls macOS launch daemons"),

    # Permission / ownership changes
    (r"\bchmod\b",                      "chmod changes file permissions"),
    (r"\bchown\b",                      "chown changes file ownership"),

    # Elevated privilege
    (r"\bsudo\b",                       "sudo runs commands with elevated privileges"),

    # Environment mutation that can redirect execution
    (r"\bexport\s+PATH=",               "Modifying PATH can redirect command execution"),
]
