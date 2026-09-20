INSERT INTO roles (role, description)
VALUES (
        'member',
        'Can create and manage their own expenses'
    ),
    (
        'approver',
        'Can additionally approve or reject anyone''s expenses'
    ),
    (
        'admin',
        'Can additionally manage membership and delete expenses'
    );
INSERT INTO role_permissions (role, permission)
VALUES -- member
    ('member', 'expense:read'),
    ('member', 'expense:create'),
    ('member', 'expense:update_own'),
    ('member', 'expense:submit_own'),
    -- approver inherits nothing automatically: list it explicitly
    ('approver', 'expense:read'),
    ('approver', 'expense:create'),
    ('approver', 'expense:update_own'),
    ('approver', 'expense:submit_own'),
    ('approver', 'expense:approve'),
    ('approver', 'expense:reject'),
    -- admin
    ('admin', 'expense:read'),
    ('admin', 'expense:create'),
    ('admin', 'expense:update_own'),
    ('admin', 'expense:update_any'),
    ('admin', 'expense:submit_own'),
    ('admin', 'expense:approve'),
    ('admin', 'expense:reject'),
    ('admin', 'expense:delete'),
    ('admin', 'member:read'),
    ('admin', 'member:manage'),
    ('admin', 'group:update');