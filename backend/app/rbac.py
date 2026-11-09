"""Roles and permissions.

The code below is the single source of truth. `sync()` mirrors it into the `roles`, `permissions` and
`role_permissions` tables on every start, so the tables are always reportable and can be migrated to PostgreSQL
unchanged. Later phases only add permissions here; nothing else needs to change.

Rule of thumb for adding a permission: name it `<area>.<action>`, grant it to the *least* number of roles that
need it, and protect the route with `security.require("<permission>")`.
"""
ADMIN, FACULTY, ALUMNI, STUDENT = "ADMIN", "FACULTY", "ALUMNI", "STUDENT"

ROLES = {
    ADMIN: "Full control, including user management and the audit log.",
    FACULTY: "Maintains alumni records, imports, exports, reminders and reports. Cannot delete records or manage users.",
    ALUMNI: "A graduate with a linked alumni record. Manages their own profile and privacy.",
    STUDENT: "A current student. Can browse what alumni have chosen to share.",
}

PERMISSIONS = {
    "alumni.read": "View alumni records, including contact details",
    "alumni.write": "Edit alumni records, unsubscribe, undo actions",
    "alumni.delete": "Delete alumni records",
    "alumni.link.manage": "Revoke or regenerate an alumnus' personal form link",
    "import.run": "Validate and commit spreadsheet imports",
    "export.run": "Export records to CSV / Excel",
    "campaign.manage": "Create, run and monitor reminder campaigns",
    "report.view": "View dashboard and analytics",
    "user.manage": "Create users, change roles, disable accounts, end sessions",
    "audit.view": "Read the audit log",
    "profile.own.read": "View my own profile and privacy setting",
    "profile.own.write": "Change my own privacy setting",
    "directory.read": "Browse profiles that are visible to my role",
}

_STAFF = {"alumni.read", "alumni.write", "alumni.link.manage", "import.run", "export.run", "campaign.manage",
          "report.view", "directory.read"}

ROLE_PERMISSIONS = {
    ADMIN: set(PERMISSIONS),
    FACULTY: set(_STAFF),
    ALUMNI: {"profile.own.read", "profile.own.write", "directory.read"},
    STUDENT: {"directory.read"},
}

STAFF_ROLES = frozenset({ADMIN, FACULTY})


def permissions_for(role):
    return ROLE_PERMISSIONS.get(role, set())


def has(role, permission):
    return permission in permissions_for(role)


def sync(c):
    """Make the database tables match this file. Idempotent."""
    for name, desc in ROLES.items():
        c.execute("INSERT INTO roles(name,description) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET description=excluded.description",
                  (name, desc))
    for name, desc in PERMISSIONS.items():
        c.execute("INSERT INTO permissions(name,description) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET description=excluded.description",
                  (name, desc))
    c.execute("DELETE FROM role_permissions")
    for role, perms in ROLE_PERMISSIONS.items():
        for p in sorted(perms):
            c.execute("INSERT INTO role_permissions(role,permission) VALUES(?,?)", (role, p))
    c.execute("DELETE FROM permissions WHERE name NOT IN (%s)" % ",".join("?" * len(PERMISSIONS)), list(PERMISSIONS))
