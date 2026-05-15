# -*- coding: utf-8 -*-
"""
Interactive Shell — Interactive interface with autocompletion.

Uses prompt_toolkit for autocompletion and history,
and Rich for colored display.

Commands: help, health, whoami, about, space, live, bank, token, backup, quit.
"""

import shlex
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from pathlib import Path

from .client import MCPClient
from .display import (
    console,
    show_error,
    show_success,
    show_warning,
    show_json,
    show_health_result,
    show_whoami_result,
    show_about_result,
    show_space_created,
    show_space_updated,
    show_rules_updated,
    show_space_list,
    show_space_info,
    show_rules,
    show_notes,
    show_bank_list,
    show_bank_content,
    show_consolidation_result,
    show_bank_write_result,
    show_bank_delete_result,
    show_bank_repair_result,
    show_bank_compact_result,
    show_graph_connected,
    show_graph_status,
    show_graph_push_result,
    show_graph_disconnected,
    show_token_created,
    show_token_list,
    show_backup_created,
    show_backup_list,
)


# =============================================================================
# Available commands (for autocompletion)
# =============================================================================

SHELL_COMMANDS = {
    "help": "Show help",
    "health": "Health status",
    "whoami": "Current token identity (name, permissions, spaces)",
    "about": "Service information",
    "space create": 'Create a space (space create <id> -d "desc" -r <rules.md> [-o owner])',
    "space update": 'Update description/owner (space update <id> -d "desc" [-o "owner"])',
    "space update-rules": "Update rules (space update-rules <id> -f <rules.md>) admin",
    "space list": "List spaces",
    "space info": "Space details (space info <id>)",
    "space rules": "Space rules (space rules <id>)",
    "space summary": "Full summary (space summary <id>)",
    "space export": "Export as tar.gz (space export <id>)",
    "space delete": "Delete a space (space delete <id> --confirm)",
    "live note": "Write a note (live note <space> <cat> <content>)",
    "live read": "Read notes (live read <space>)",
    "live search": "Search (live search <space> <query>)",
    "bank list": "List bank files (bank list <space>)",
    "bank read": "Read a bank file (bank read <space> <file>)",
    "bank read-all": "Read entire bank (bank read-all <space>)",
    "bank consolidate": "Consolidate via LLM (bank consolidate <space>)",
    "bank write": "Write a bank file (bank write <space> <file> -f <path.md>) admin",
    "bank delete": "Delete a bank file (bank delete <space> <file>) admin",
    "bank repair": "Repair corrupted names (bank repair <space> [--apply]) admin",
    "bank compact": "Compact oversized files (bank compact <space> [--apply]) admin",
    "token create": "Create a token (token create <name> -p <read|read,write|read,write,manage|...admin> [--email <email>])",
    "token update": "Update a token (token update <hash> [--permissions ...] [--space-ids ... | --add-spaces ... --remove-spaces ...])",
    "token list": "List tokens (token list [--name-contains x] [--has-space y] [--no-revoked])",
    "token bulk-update": "Update N tokens (token bulk-update --name-contains agent --add-spaces new --confirm) issue #13",
    "token revoke": "Revoke a token (token revoke <hash>)",
    "token delete": "Physically delete a token (token delete <hash>)",
    "token purge": "Purge revoked tokens (token purge [--all])",
    "graph connect": "Connect to Graph Memory (graph connect <space> <url> <token> <memory_id> [ontology])",
    "graph push": "Push bank to graph (graph push <space>)",
    "graph status": "Graph Memory connection status (graph status <space>)",
    "graph disconnect": "Disconnect from Graph Memory (graph disconnect <space>)",
    "backup create": "Create a backup (backup create <space> or backup create --all)",
    "backup list": "List backups",
    "backup restore": "Restore (backup restore <id> --confirm)",
    "backup download": "Download a backup (backup download <id>)",
    "backup delete": "Delete (backup delete <id> --confirm)",
    "gc": "Garbage Collector (gc [--space-id <id>] [--confirm])",
    "quit": "Quit",
}


# =============================================================================
# Command dispatcher
# =============================================================================

# Subcommands by verb (for contextual help)
VERB_SUBCOMMANDS = {
    "space": {
        k.split(" ", 1)[1]: v
        for k, v in SHELL_COMMANDS.items()
        if k.startswith("space ")
    },
    "live": {
        k.split(" ", 1)[1]: v
        for k, v in SHELL_COMMANDS.items()
        if k.startswith("live ")
    },
    "bank": {
        k.split(" ", 1)[1]: v
        for k, v in SHELL_COMMANDS.items()
        if k.startswith("bank ")
    },
    "token": {
        k.split(" ", 1)[1]: v
        for k, v in SHELL_COMMANDS.items()
        if k.startswith("token ")
    },
    "graph": {
        k.split(" ", 1)[1]: v
        for k, v in SHELL_COMMANDS.items()
        if k.startswith("graph ")
    },
    "backup": {
        k.split(" ", 1)[1]: v
        for k, v in SHELL_COMMANDS.items()
        if k.startswith("backup ")
    },
}


async def dispatch(client: MCPClient, user_input: str, json_output: bool):
    """Route a command to the appropriate handler."""
    try:
        parts = shlex.split(user_input.strip())
    except ValueError:
        # Fallback if unclosed quotes
        parts = user_input.strip().split()
    if not parts:
        return

    cmd = parts[0].lower()
    args = parts[1:]

    # ── Help (global or contextual) ──
    if cmd == "help":
        if args and args[0] in VERB_SUBCOMMANDS:
            _show_verb_help(args[0])
        else:
            _show_help()
        return

    # ── System ──
    if cmd == "health":
        result = await client.call_tool("system_health", {})
        (show_json if json_output else show_health_result)(result)

    elif cmd == "whoami":
        result = await client.call_tool("system_whoami", {})
        (show_json if json_output else show_whoami_result)(result)

    elif cmd == "about":
        result = await client.call_tool("system_about", {})
        (show_json if json_output else show_about_result)(result)

    # ── Verbs with subcommands ──
    elif cmd == "space":
        if not args or args[0] == "help":
            _show_verb_help("space")
        else:
            await _handle_space(client, args, json_output)

    elif cmd == "live":
        if not args or args[0] == "help":
            _show_verb_help("live")
        else:
            await _handle_live(client, args, json_output)

    elif cmd == "bank":
        if not args or args[0] == "help":
            _show_verb_help("bank")
        else:
            await _handle_bank(client, args, json_output)

    elif cmd == "graph":
        if not args or args[0] == "help":
            _show_verb_help("graph")
        else:
            await _handle_graph(client, args, json_output)

    elif cmd == "token":
        if not args or args[0] == "help":
            _show_verb_help("token")
        else:
            await _handle_token(client, args, json_output)

    elif cmd == "backup":
        if not args or args[0] == "help":
            _show_verb_help("backup")
        else:
            await _handle_backup(client, args, json_output)

    elif cmd == "gc":
        gc_args = {
            "space_id": "",
            "max_age_days": 7,
            "confirm": False,
            "delete_only": False,
        }
        for i, a in enumerate(args):
            if a == "--space-id" and i + 1 < len(args):
                gc_args["space_id"] = args[i + 1]
            elif a == "--max-age-days" and i + 1 < len(args):
                gc_args["max_age_days"] = int(args[i + 1])
            elif a == "--confirm":
                gc_args["confirm"] = True
            elif a == "--delete-only":
                gc_args["delete_only"] = True
        result = await client.call_tool("admin_gc_notes", gc_args)
        show_json(result)

    else:
        show_warning(f"Unknown command: '{user_input}'. Type 'help'.")


# =============================================================================
# Handlers by category
# =============================================================================


async def _handle_space(client, args, json_out):
    """Handler for space commands."""
    sub = args[0] if args else ""

    if sub == "create":
        # Parse named options (like CLI Click)
        description = ""
        rules = ""
        rules_file = ""
        owner = ""
        remaining = args[1:]  # after "create"
        i = 0
        positional = []
        while i < len(remaining):
            flag = remaining[i]
            if flag in ("-d", "--description") and i + 1 < len(remaining):
                description = remaining[i + 1]
                i += 2
            elif flag in ("-r", "--rules-file") and i + 1 < len(remaining):
                rules_file = remaining[i + 1]
                i += 2
            elif flag == "--rules" and i + 1 < len(remaining):
                rules = remaining[i + 1]
                i += 2
            elif flag in ("-o", "--owner") and i + 1 < len(remaining):
                owner = remaining[i + 1]
                i += 2
            else:
                positional.append(flag)
                i += 1

        # Read rules file if -r/--rules-file specified
        if rules_file and not rules:
            try:
                rules = Path(rules_file).read_text(encoding="utf-8")
            except Exception as e:
                show_error(f"Cannot read rules file: {e}")
                return

        # Backward compat: positional form space create <id> <desc> <rules>
        if not description and not rules and len(positional) >= 3:
            space_id = positional[0]
            description = positional[1]
            rules = " ".join(positional[2:])
        else:
            space_id = positional[0] if positional else ""

        if not space_id:
            console.print(
                '[yellow]Usage: space create <space_id> -d "description" -r <rules_file.md>[/yellow]'
            )
            console.print(
                "[yellow]   or: space create <space_id> <description> <rules_inline>[/yellow]"
            )
            return
        if not rules:
            show_error('Rules required: -r <file.md> or --rules "inline content"')
            return

        tool_args = {"space_id": space_id, "description": description, "rules": rules}
        if owner:
            tool_args["owner"] = owner
        result = await client.call_tool("space_create", tool_args)
        (show_json if json_out else show_space_created)(result) if result.get(
            "status"
        ) == "created" else show_error(result.get("message", "?"))

    elif sub == "update" and len(args) >= 2:
        space_id = args[1]
        # Parse named options
        description = ""
        owner = ""
        for i, a in enumerate(args):
            if a in ("-d", "--description") and i + 1 < len(args):
                description = args[i + 1]
            elif a in ("-o", "--owner") and i + 1 < len(args):
                owner = args[i + 1]
        if not description and not owner:
            console.print(
                '[yellow]Usage: space update <space_id> -d "description" [-o "owner"][/yellow]'
            )
            return
        tool_args = {"space_id": space_id}
        if description:
            tool_args["description"] = description
        if owner:
            tool_args["owner"] = owner
        result = await client.call_tool("space_update", tool_args)
        if result.get("status") == "ok":
            show_space_updated(result)
        else:
            show_error(result.get("message", "Error"))
        return

    elif sub == "update-rules" and len(args) >= 2:
        space_id = args[1]
        rules_file = ""
        for i, a in enumerate(args):
            if a in ("-f", "--rules-file") and i + 1 < len(args):
                rules_file = args[i + 1]
        if not rules_file:
            console.print(
                "[yellow]Usage: space update-rules <space_id> -f <rules.md>[/yellow]"
            )
            return
        try:
            rules_content = Path(rules_file).read_text(encoding="utf-8")
        except Exception as e:
            show_error(f"Cannot read {rules_file}: {e}")
            return
        result = await client.call_tool(
            "space_update_rules", {"space_id": space_id, "rules": rules_content}
        )
        (show_json if json_out else show_rules_updated)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "list":
        result = await client.call_tool("space_list", {})
        (show_json if json_out else show_space_list)(result)

    elif sub == "info" and len(args) >= 2:
        result = await client.call_tool("space_info", {"space_id": args[1]})
        (show_json if json_out else show_space_info)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "rules" and len(args) >= 2:
        result = await client.call_tool("space_rules", {"space_id": args[1]})
        (show_json if json_out else show_rules)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "summary" and len(args) >= 2:
        result = await client.call_tool("space_summary", {"space_id": args[1]})
        show_json(result)

    elif sub == "export" and len(args) >= 2:
        result = await client.call_tool("space_export", {"space_id": args[1]})
        show_json(result)

    elif sub == "delete" and len(args) >= 2:
        confirm = "--confirm" in args
        if not confirm:
            show_warning(
                f"⚠️  Deleting '{args[1]}' — add --confirm to confirm:"
            )
            show_warning(f"   space delete {args[1]} --confirm")
            return
        result = await client.call_tool(
            "space_delete", {"space_id": args[1], "confirm": True}
        )
        show_success("Deleted") if result.get("status") == "deleted" else show_error(
            result.get("message", "?")
        )

    else:
        show_warning(
            "Usage: space [create|update|list|info|rules|summary|export|delete] ..."
        )


async def _handle_live(client, args, json_out):
    """Handler for live commands."""
    sub = args[0] if args else ""

    if sub == "note" and len(args) >= 4:
        result = await client.call_tool(
            "live_note",
            {
                "space_id": args[1],
                "category": args[2],
                "content": " ".join(args[3:]),
            },
        )
        show_success(f"Note: {result.get('filename', '?')}") if result.get(
            "status"
        ) == "created" else show_error(result.get("message", "?"))

    elif sub == "read" and len(args) >= 2:
        result = await client.call_tool("live_read", {"space_id": args[1], "limit": 20})
        (show_json if json_out else show_notes)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "search" and len(args) >= 3:
        result = await client.call_tool(
            "live_search",
            {
                "space_id": args[1],
                "query": " ".join(args[2:]),
            },
        )
        (show_json if json_out else show_notes)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    else:
        show_warning("Usage: live [note|read|search] ...")


async def _handle_bank(client, args, json_out):
    """Handler for bank commands."""
    sub = args[0] if args else ""

    if sub == "list" and len(args) >= 2:
        result = await client.call_tool("bank_list", {"space_id": args[1]})
        (show_json if json_out else show_bank_list)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "read" and len(args) >= 3:
        result = await client.call_tool(
            "bank_read", {"space_id": args[1], "filename": args[2]}
        )
        (show_json if json_out else show_bank_content)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "read-all" and len(args) >= 2:
        result = await client.call_tool("bank_read_all", {"space_id": args[1]})
        if json_out:
            show_json(result)
        elif result.get("status") == "ok":
            for f in result.get("files", []):
                show_bank_content(f)
        else:
            show_error(result.get("message", "?"))

    elif sub == "consolidate" and len(args) >= 2:
        console.print("[dim]Consolidation in progress...[/dim]")
        result = await client.call_tool("bank_consolidate", {"space_id": args[1]})
        (show_json if json_out else show_consolidation_result)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "write" and len(args) >= 3:
        space_id = args[1]
        filename = args[2]
        content_val = ""
        content_file = ""
        remaining = args[3:]
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in ("-f", "--content-file") and i + 1 < len(remaining):
                content_file = remaining[i + 1]
                i += 2
            elif flag in ("-c", "--content") and i + 1 < len(remaining):
                content_val = remaining[i + 1]
                i += 2
            else:
                # Inline content without flag
                if not content_val:
                    content_val = " ".join(remaining[i:])
                    break
                i += 1
        if content_file and not content_val:
            try:
                content_val = Path(content_file).read_text(encoding="utf-8")
            except Exception as e:
                show_error(f"Cannot read {content_file}: {e}")
                return
        if not content_val:
            console.print(
                "[yellow]Usage: bank write <space> <filename> -f <path.md>[/yellow]"
            )
            console.print(
                '[yellow]  or: bank write <space> <filename> -c "inline content"[/yellow]'
            )
            return
        result = await client.call_tool(
            "bank_write",
            {
                "space_id": space_id,
                "filename": filename,
                "content": content_val,
            },
        )
        (show_json if json_out else show_bank_write_result)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "delete" and len(args) >= 3:
        result = await client.call_tool(
            "bank_delete",
            {
                "space_id": args[1],
                "filename": args[2],
            },
        )
        (show_json if json_out else show_bank_delete_result)(result) if result.get(
            "status"
        ) == "deleted" else show_error(result.get("message", "?"))

    elif sub == "repair" and len(args) >= 2:
        dry_run = "--apply" not in args
        result = await client.call_tool(
            "bank_repair",
            {
                "space_id": args[1],
                "dry_run": dry_run,
            },
        )
        (show_json if json_out else show_bank_repair_result)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "compact" and len(args) >= 2:
        dry_run = "--apply" not in args
        if dry_run:
            console.print("[dim]Dry-run mode — analysis without modifications.[/dim]")
        else:
            console.print(
                "[dim]Compaction in progress... (may take several seconds per file)[/dim]"
            )
        result = await client.call_tool(
            "bank_compact",
            {
                "space_id": args[1],
                "dry_run": dry_run,
            },
        )
        (show_json if json_out else show_bank_compact_result)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    else:
        show_warning(
            "Usage: bank [list|read|read-all|consolidate|compact|write|delete|repair] ..."
        )


# Valid permissions (shared with token handler)
_VALID_PERMS = {"read", "read,write", "read,write,manage", "read,write,manage,admin"}


def _validate_permissions(perms: str) -> bool:
    """Checks that permissions are valid."""
    return perms in _VALID_PERMS


async def _handle_token(client, args, json_out):
    """Handler for token commands."""
    sub = args[0] if args else ""

    if sub == "create" and len(args) >= 2:
        name = args[1]
        # Parse named flags --permissions/-p, --email/-e, --space-ids/-s
        perms = ""
        email = ""
        space_ids = ""
        expires = 0
        remaining = args[2:]
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in ("--permissions", "-p") and i + 1 < len(remaining):
                perms = remaining[i + 1]
                i += 2
            elif flag in ("--email", "-e") and i + 1 < len(remaining):
                email = remaining[i + 1]
                i += 2
            elif flag in ("--space-ids", "-s") and i + 1 < len(remaining):
                space_ids = remaining[i + 1]
                i += 2
            elif flag in ("--expires-in-days",) and i + 1 < len(remaining):
                expires = int(remaining[i + 1])
                i += 2
            else:
                # Backward compat: if no flag, treat as positional permissions
                if not perms and _validate_permissions(flag):
                    perms = flag
                i += 1
        if not perms:
            show_error(
                "Permissions required: --permissions/-p <read|read,write|read,write,manage|read,write,manage,admin>"
            )
            show_warning("Ex: token create KSE -p read,write --email kevin@example.com")
            return
        if not _validate_permissions(perms):
            show_error(f"Invalid permissions: '{perms}'")
            show_warning("Accepted values: read | read,write | read,write,manage | read,write,manage,admin")
            return
        mcp_args = {"name": name, "permissions": perms}
        if email:
            mcp_args["email"] = email
        if space_ids:
            mcp_args["space_ids"] = space_ids
        if expires:
            mcp_args["expires_in_days"] = expires
        result = await client.call_tool("admin_create_token", mcp_args)
        (show_json if json_out else show_token_created)(result) if result.get(
            "status"
        ) == "created" else show_error(result.get("message", "?"))

    elif sub == "update" and len(args) >= 2:
        token_hash = args[1]
        # Parse flags --permissions, --space-ids, --add-spaces, --remove-spaces, --email
        mcp_args = {"token_hash": token_hash}
        remaining = args[2:]
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in ("--permissions", "-p") and i + 1 < len(remaining):
                perms = remaining[i + 1]
                if not _validate_permissions(perms):
                    show_error(f"Invalid permissions: '{perms}'")
                    show_warning(
                        "Accepted values: read | read,write | read,write,manage | read,write,manage,admin"
                    )
                    return
                mcp_args["permissions"] = perms
                i += 2
            elif flag in ("--space-ids", "-s") and i + 1 < len(remaining):
                mcp_args["space_ids"] = remaining[i + 1]
                i += 2
            elif flag in ("--add-spaces", "-a") and i + 1 < len(remaining):
                mcp_args["space_ids_add"] = remaining[i + 1]
                i += 2
            elif flag in ("--remove-spaces", "-r") and i + 1 < len(remaining):
                mcp_args["space_ids_remove"] = remaining[i + 1]
                i += 2
            elif flag in ("--email", "-e") and i + 1 < len(remaining):
                mcp_args["email"] = remaining[i + 1]
                i += 2
            else:
                i += 1
        if len(mcp_args) <= 1:
            show_error(
                "Nothing to update. Use --permissions, --space-ids, "
                "--add-spaces, --remove-spaces and/or --email."
            )
            show_warning("Ex: token update sha256:a8c5 --email user@example.com")
            show_warning("Ex: token update sha256:a8c5 -a new-space  (delta)")
            return
        # Client-side guard: replacement and delta are incompatible
        if "space_ids" in mcp_args and (
            "space_ids_add" in mcp_args or "space_ids_remove" in mcp_args
        ):
            show_error(
                "--space-ids (replacement) is incompatible with "
                "--add-spaces / --remove-spaces (delta)."
            )
            return
        result = await client.call_tool("admin_update_token", mcp_args)
        show_success(result.get("message", "Token updated")) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "list":
        # Issue #13 : filtres optionnels --name-contains, --has-space, --no-revoked
        list_args = {
            "name_contains": "",
            "has_space": "",
            "include_revoked": True,
        }
        remaining = args[1:]
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in ("--name-contains", "-n") and i + 1 < len(remaining):
                list_args["name_contains"] = remaining[i + 1]
                i += 2
            elif flag in ("--has-space",) and i + 1 < len(remaining):
                # Note: -s is already taken by --space-ids in update; no short alias here
                list_args["has_space"] = remaining[i + 1]
                i += 2
            elif flag == "--no-revoked":
                list_args["include_revoked"] = False
                i += 1
            else:
                i += 1
        result = await client.call_tool("admin_list_tokens", list_args)
        (show_json if json_out else show_token_list)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "bulk-update":
        # Issue #13 + review PR #14 : admin_bulk_update_tokens
        bulk_args = {
            "names": "",
            "name_contains": "",
            "has_space": "",
            "space_ids_add": "",
            "space_ids_remove": "",
            "include_revoked": False,
        }
        confirm = False
        remaining = args[1:]
        i = 0
        while i < len(remaining):
            flag = remaining[i]
            if flag in ("--names",) and i + 1 < len(remaining):
                bulk_args["names"] = remaining[i + 1]
                i += 2
            elif flag in ("--name-contains", "-n") and i + 1 < len(remaining):
                bulk_args["name_contains"] = remaining[i + 1]
                i += 2
            elif flag in ("--has-space", "-s") and i + 1 < len(remaining):
                bulk_args["has_space"] = remaining[i + 1]
                i += 2
            elif flag in ("--add-spaces", "-a") and i + 1 < len(remaining):
                bulk_args["space_ids_add"] = remaining[i + 1]
                i += 2
            elif flag in ("--remove-spaces", "-r") and i + 1 < len(remaining):
                bulk_args["space_ids_remove"] = remaining[i + 1]
                i += 2
            elif flag in ("--permissions", "-p") and i + 1 < len(remaining):
                perms = remaining[i + 1]
                if not _validate_permissions(perms):
                    show_error(f"Invalid permissions: '{perms}'")
                    return
                bulk_args["permissions"] = perms
                i += 2
            elif flag in ("--email", "-e") and i + 1 < len(remaining):
                bulk_args["email"] = remaining[i + 1]
                i += 2
            elif flag == "--include-revoked":
                bulk_args["include_revoked"] = True
                i += 1
            elif flag == "--confirm":
                confirm = True
                i += 1
            else:
                i += 1
        # Shell-side validations (server also re-validates)
        if (
            not bulk_args["names"]
            and not bulk_args["name_contains"]
            and not bulk_args["has_space"]
        ):
            show_error(
                "At least one filter required: --names, --name-contains or --has-space."
            )
            return
        if not (
            bulk_args.get("space_ids_add")
            or bulk_args.get("space_ids_remove")
            or bulk_args.get("permissions")
            or bulk_args.get("email")
        ):
            show_error(
                "At least one operation required: --add-spaces, --remove-spaces, "
                "--permissions or --email."
            )
            return
        if not confirm:
            show_warning(
                "⚠️  Dry-run: add --confirm to execute the bulk-update."
            )
            return
        result = await client.call_tool("admin_bulk_update_tokens", bulk_args)
        if result.get("status") == "ok":
            from .display import show_bulk_update_result
            (show_json if json_out else show_bulk_update_result)(result)
        else:
            show_error(result.get("message", "?"))

    elif sub == "revoke" and len(args) >= 2:
        result = await client.call_tool("admin_revoke_token", {"token_hash": args[1]})
        show_success("Token revoked") if result.get("status") == "ok" else show_error(
            result.get("message", "?")
        )

    elif sub == "delete" and len(args) >= 2:
        result = await client.call_tool("admin_delete_token", {"token_hash": args[1]})
        show_success(result.get("message", "Token deleted")) if result.get(
            "status"
        ) == "deleted" else show_error(result.get("message", "?"))

    elif sub == "purge":
        confirm = "--confirm" in args
        purge_all = "--all" in args
        if not confirm:
            mode = "ALL tokens" if purge_all else "revoked tokens"
            show_warning(f"⚠️  Purge {mode} — add --confirm to confirm:")
            show_warning(f"   token purge {'--all ' if purge_all else ''}--confirm")
            return
        revoked_only = not purge_all
        result = await client.call_tool(
            "admin_purge_tokens", {"revoked_only": revoked_only}
        )
        if result.get("status") == "ok":
            show_success(
                f"{result.get('deleted', 0)} token(s) deleted, {result.get('remaining', 0)} remaining"
            )
        else:
            show_error(result.get("message", "?"))

    else:
        show_warning(
            "Usage: token [create|update|list|bulk-update|revoke|delete|purge] ..."
        )


async def _handle_graph(client, args, json_out):
    """Handler for graph commands."""
    sub = args[0] if args else ""

    if sub == "connect" and len(args) >= 5:
        ontology = args[5] if len(args) >= 6 else "general"
        result = await client.call_tool(
            "graph_connect",
            {
                "space_id": args[1],
                "url": args[2],
                "token": args[3],
                "memory_id": args[4],
                "ontology": ontology,
            },
        )
        (show_json if json_out else show_graph_connected)(result) if result.get(
            "status"
        ) == "connected" else show_error(result.get("message", "?"))

    elif sub == "push" and len(args) >= 2:
        console.print("[dim]Push in progress... (may take several minutes)[/dim]")
        result = await client.call_tool("graph_push", {"space_id": args[1]})
        (show_json if json_out else show_graph_push_result)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "status" and len(args) >= 2:
        result = await client.call_tool("graph_status", {"space_id": args[1]})
        (show_json if json_out else show_graph_status)(result) if result.get(
            "status"
        ) == "ok" else show_error(result.get("message", "?"))

    elif sub == "disconnect" and len(args) >= 2:
        result = await client.call_tool("graph_disconnect", {"space_id": args[1]})
        (show_json if json_out else show_graph_disconnected)(result) if result.get(
            "status"
        ) == "disconnected" else show_error(result.get("message", "?"))

    else:
        show_warning("Usage: graph [connect|push|status|disconnect] ...")


async def _handle_backup(client, args, json_out):
    """Handler for backup commands."""
    sub = args[0] if args else ""

    if sub == "create":
        # Support --all for backing up all spaces
        backup_all = "--all" in args
        if backup_all:
            console.print("[dim]Backing up all spaces...[/dim]")
            result = await client.call_tool("backup_create", {"space_id": ""})
            from .display import show_backup_all_result

            (show_json if json_out else show_backup_all_result)(result) if result.get(
                "status"
            ) == "ok" else show_error(result.get("message", "?"))
        elif len(args) >= 2:
            result = await client.call_tool("backup_create", {"space_id": args[1]})
            (show_json if json_out else show_backup_created)(result) if result.get(
                "status"
            ) == "created" else show_error(result.get("message", "?"))
        else:
            console.print(
                "[yellow]Usage: backup create <space_id> or backup create --all[/yellow]"
            )

    elif sub == "list":
        result = await client.call_tool(
            "backup_list", {"space_id": args[1] if len(args) >= 2 else ""}
        )
        (show_json if json_out else show_backup_list)(result)

    elif sub == "restore" and len(args) >= 2:
        confirm = "--confirm" in args
        if not confirm:
            show_warning(
                f"⚠️  Restoring '{args[1]}' — add --confirm to confirm:"
            )
            show_warning(f"   backup restore {args[1]} --confirm")
            return
        result = await client.call_tool(
            "backup_restore", {"backup_id": args[1], "confirm": True}
        )
        show_success("Restored") if result.get("status") == "ok" else show_error(
            result.get("message", "?")
        )

    elif sub == "download" and len(args) >= 2:
        result = await client.call_tool("backup_download", {"backup_id": args[1]})
        show_json(result)

    elif sub == "delete" and len(args) >= 2:
        confirm = "--confirm" in args
        if not confirm:
            show_warning(
                f"⚠️  Deleting '{args[1]}' — add --confirm to confirm:"
            )
            show_warning(f"   backup delete {args[1]} --confirm")
            return
        result = await client.call_tool(
            "backup_delete", {"backup_id": args[1], "confirm": True}
        )
        show_success("Deleted") if result.get("status") == "deleted" else show_error(
            result.get("message", "?")
        )

    else:
        show_warning("Usage: backup [create|list|restore|download|delete] ...")


# =============================================================================
# Help
# =============================================================================


def _show_help():
    """Displays the global shell help."""
    from rich.table import Table

    table = Table(title="🐚 Commands Live Memory", show_header=True)
    table.add_column("Command", style="cyan bold", min_width=25)
    table.add_column("Description")
    for cmd, desc in SHELL_COMMANDS.items():
        table.add_row(cmd, desc)
    table.add_row("", "")
    table.add_row("[dim]--json[/dim]", "[dim]Append for JSON output[/dim]")
    table.add_row(
        "[dim]help <verb>[/dim]", "[dim]Help for a verb (e.g. help space)[/dim]"
    )
    console.print(table)


def _show_verb_help(verb: str):
    """Displays help for a specific verb (subcommands)."""
    from rich.table import Table

    subs = VERB_SUBCOMMANDS.get(verb, {})
    if not subs:
        show_warning(f"No subcommands for '{verb}'.")
        return
    table = Table(title=f"📖 {verb} — subcommands", show_header=True)
    table.add_column("Command", style="cyan bold", min_width=15)
    table.add_column("Usage")
    for sub, desc in subs.items():
        table.add_row(f"{verb} {sub}", desc)
    console.print(table)


# =============================================================================
# Main loop
# =============================================================================


async def run_shell(url: str, token: str):
    """Starts the Live Memory interactive shell."""
    client = MCPClient(url, token)

    # Autocompletion with all keywords
    words = list(SHELL_COMMANDS.keys()) + [
        "--json",
        "--confirm",
        "--all",
        "--apply",
        "--permissions",
        "-p",
        "--space-ids",
        "-s",
        "--add-spaces",
        "-a",
        "--remove-spaces",
        "-r",
        "--name-contains",
        "-n",
        "--has-space",
        "--no-revoked",
        "--names",
        "--description",
        "-d",
        "--rules-file",
        "--rules",
        "--owner",
        "-o",
        "--email",
        "-e",
        "--content-file",
        "-f",
        "--content",
        "-c",
        "read",
        "read,write",
        "read,write,manage",
        "read,write,manage,admin",
    ]
    completer = WordCompleter(words, ignore_case=True)

    history_path = Path.home() / ".live_mem_shell_history"
    session = PromptSession(
        history=FileHistory(str(history_path)),
        completer=completer,
    )

    console.print(
        f"\n[bold cyan]🧠 Live Memory Shell[/bold cyan] — [green]{url}[/green]"
    )
    console.print("[dim]Type 'help' for help, 'quit' to exit.[/dim]\n")

    while True:
        try:
            user_input = await session.prompt_async("live-mem> ")
            if not user_input.strip():
                continue

            # Detect --json
            json_output = "--json" in user_input
            clean_input = user_input.replace("--json", "").strip()

            # Quit
            if clean_input.lower() in ("quit", "exit"):
                console.print("[dim]Goodbye 👋[/dim]")
                break

            await dispatch(client, clean_input, json_output)

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — type 'quit' to exit[/dim]")
        except EOFError:
            console.print("[dim]Goodbye 👋[/dim]")
            break
        except Exception as e:
            show_error(f"Error: {e}")
