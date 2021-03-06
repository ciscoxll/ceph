# -*- coding: utf-8 -*-
# pylint: disable=dangerous-default-value,too-many-public-methods
from __future__ import absolute_import

import errno
import json
import unittest

from .. import mgr
from ..security import Scope, Permission
from ..services.access_control import handle_access_control_command, \
                                      load_access_control_db, \
                                      password_hash, AccessControlDB, \
                                      SYSTEM_ROLES


class CmdException(Exception):
    def __init__(self, retcode, message):
        super(CmdException, self).__init__(message)
        self.retcode = retcode


class AccessControlTest(unittest.TestCase):
    CONFIG_KEY_DICT = {}

    @classmethod
    def mock_set_config(cls, attr, val):
        cls.CONFIG_KEY_DICT[attr] = val

    @classmethod
    def mock_get_config(cls, attr, default):
        return cls.CONFIG_KEY_DICT.get(attr, default)

    @classmethod
    def setUpClass(cls):
        mgr.set_config.side_effect = cls.mock_set_config
        mgr.get_config.side_effect = cls.mock_get_config
        mgr.set_store.side_effect = cls.mock_set_config
        mgr.get_store.side_effect = cls.mock_get_config

    def setUp(self):
        self.CONFIG_KEY_DICT.clear()
        load_access_control_db()

    @classmethod
    def exec_cmd(cls, cmd, **kwargs):
        cmd_dict = {'prefix': 'dashboard {}'.format(cmd)}
        cmd_dict.update(kwargs)
        ret, out, err = handle_access_control_command(cmd_dict)
        if ret < 0:
            raise CmdException(ret, err)
        try:
            return json.loads(out)
        except ValueError:
            return out

    def load_persistent_db(self):
        config_key = AccessControlDB.accessdb_config_key()
        self.assertIn(config_key, self.CONFIG_KEY_DICT)
        db_json = self.CONFIG_KEY_DICT[config_key]
        db = json.loads(db_json)
        return db

    def validate_persistent_role(self, rolename, scopes_permissions,
                                 description=None):
        db = self.load_persistent_db()
        self.assertIn('roles', db)
        self.assertIn(rolename, db['roles'])
        self.assertEqual(db['roles'][rolename]['name'], rolename)
        self.assertEqual(db['roles'][rolename]['description'], description)
        self.assertDictEqual(db['roles'][rolename]['scopes_permissions'],
                             scopes_permissions)

    def validate_persistent_no_role(self, rolename):
        db = self.load_persistent_db()
        self.assertIn('roles', db)
        self.assertNotIn(rolename, db['roles'])

    def validate_persistent_user(self, username, roles, password=None,
                                 name=None, email=None):
        db = self.load_persistent_db()
        self.assertIn('users', db)
        self.assertIn(username, db['users'])
        self.assertEqual(db['users'][username]['username'], username)
        self.assertListEqual(db['users'][username]['roles'], roles)
        if password:
            self.assertEqual(db['users'][username]['password'], password)
        if name:
            self.assertEqual(db['users'][username]['name'], name)
        if email:
            self.assertEqual(db['users'][username]['email'], email)

    def validate_persistent_no_user(self, username):
        db = self.load_persistent_db()
        self.assertIn('users', db)
        self.assertNotIn(username, db['users'])

    def test_create_role(self):
        role = self.exec_cmd('ac-role-create', rolename='test_role')
        self.assertDictEqual(role, {'name': 'test_role', 'description': None,
                                    'scopes_permissions': {}})
        self.validate_persistent_role('test_role', {})

    def test_create_role_with_desc(self):
        role = self.exec_cmd('ac-role-create', rolename='test_role',
                             description='Test Role')
        self.assertDictEqual(role, {'name': 'test_role',
                                    'description': 'Test Role',
                                    'scopes_permissions': {}})
        self.validate_persistent_role('test_role', {}, 'Test Role')

    def test_create_duplicate_role(self):
        self.test_create_role()

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-create', rolename='test_role')

        self.assertEqual(ctx.exception.retcode, -errno.EEXIST)
        self.assertEqual(str(ctx.exception), "Role 'test_role' already exists")

    def test_delete_role(self):
        self.test_create_role()
        out = self.exec_cmd('ac-role-delete', rolename='test_role')
        self.assertEqual(out, "Role 'test_role' deleted")
        self.validate_persistent_no_role('test_role')

    def test_delete_nonexistent_role(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-delete', rolename='test_role')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "Role 'test_role' does not exist")

    def test_show_single_role(self):
        self.test_create_role()
        role = self.exec_cmd('ac-role-show', rolename='test_role')
        self.assertDictEqual(role, {'name': 'test_role', 'description': None,
                                    'scopes_permissions': {}})

    def test_show_nonexistent_role(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-show', rolename='test_role')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "Role 'test_role' does not exist")

    def test_show_system_roles(self):
        roles = self.exec_cmd('ac-role-show')
        self.assertEqual(len(roles), len(SYSTEM_ROLES))
        for role in roles:
            self.assertIn(role, SYSTEM_ROLES)

    def test_show_system_role(self):
        role = self.exec_cmd('ac-role-show', rolename="read-only")
        self.assertEqual(role['name'], 'read-only')
        self.assertEqual(role['description'], 'Read-Only')

    def test_delete_system_role(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-delete', rolename='administrator')

        self.assertEqual(ctx.exception.retcode, -errno.EPERM)
        self.assertEqual(str(ctx.exception),
                         "Cannot delete system role 'administrator'")

    def test_add_role_scope_perms(self):
        self.test_create_role()
        self.exec_cmd('ac-role-add-scope-perms', rolename='test_role',
                      scopename=Scope.POOL,
                      permissions=[Permission.READ, Permission.DELETE])
        role = self.exec_cmd('ac-role-show', rolename='test_role')
        self.assertDictEqual(role, {'name': 'test_role',
                                    'description': None,
                                    'scopes_permissions': {
                                        Scope.POOL: [Permission.DELETE,
                                                     Permission.READ]
                                    }})
        self.validate_persistent_role('test_role', {
            Scope.POOL: [Permission.DELETE, Permission.READ]
        })

    def test_del_role_scope_perms(self):
        self.test_add_role_scope_perms()
        self.exec_cmd('ac-role-add-scope-perms', rolename='test_role',
                      scopename=Scope.MONITOR,
                      permissions=[Permission.READ, Permission.CREATE])
        self.validate_persistent_role('test_role', {
            Scope.POOL: [Permission.DELETE, Permission.READ],
            Scope.MONITOR: [Permission.CREATE, Permission.READ]
        })
        self.exec_cmd('ac-role-del-scope-perms', rolename='test_role',
                      scopename=Scope.POOL)
        role = self.exec_cmd('ac-role-show', rolename='test_role')
        self.assertDictEqual(role, {'name': 'test_role',
                                    'description': None,
                                    'scopes_permissions': {
                                        Scope.MONITOR: [Permission.CREATE,
                                                        Permission.READ]
                                    }})
        self.validate_persistent_role('test_role', {
            Scope.MONITOR: [Permission.CREATE, Permission.READ]
        })

    def test_add_role_scope_perms_nonexistent_role(self):

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-add-scope-perms', rolename='test_role',
                          scopename='pool',
                          permissions=['read', 'delete'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "Role 'test_role' does not exist")

    def test_add_role_invalid_scope_perms(self):
        self.test_create_role()

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-add-scope-perms', rolename='test_role',
                          scopename='invalidscope',
                          permissions=['read', 'delete'])

        self.assertEqual(ctx.exception.retcode, -errno.EINVAL)
        self.assertEqual(str(ctx.exception),
                         "Scope 'invalidscope' is not valid\n Possible values: "
                         "{}".format(Scope.all_scopes()))

    def test_add_role_scope_invalid_perms(self):
        self.test_create_role()

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-add-scope-perms', rolename='test_role',
                          scopename='pool', permissions=['invalidperm'])

        self.assertEqual(ctx.exception.retcode, -errno.EINVAL)
        self.assertEqual(str(ctx.exception),
                         "Permission 'invalidperm' is not valid\n Possible "
                         "values: {}".format(Permission.all_permissions()))

    def test_del_role_scope_perms_nonexistent_role(self):

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-del-scope-perms', rolename='test_role',
                          scopename='pool')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "Role 'test_role' does not exist")

    def test_del_role_nonexistent_scope_perms(self):
        self.test_add_role_scope_perms()

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-del-scope-perms', rolename='test_role',
                          scopename='nonexistentscope')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception),
                         "There are no permissions for scope 'nonexistentscope' "
                         "in role 'test_role'")

    def test_not_permitted_add_role_scope_perms(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-add-scope-perms', rolename='read-only',
                          scopename='pool', permissions=['read', 'delete'])

        self.assertEqual(ctx.exception.retcode, -errno.EPERM)
        self.assertEqual(str(ctx.exception),
                         "Cannot update system role 'read-only'")

    def test_not_permitted_del_role_scope_perms(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-del-scope-perms', rolename='read-only',
                          scopename='pool')

        self.assertEqual(ctx.exception.retcode, -errno.EPERM)
        self.assertEqual(str(ctx.exception),
                         "Cannot update system role 'read-only'")

    def test_create_user(self, username='admin', rolename=None):
        user = self.exec_cmd('ac-user-create', username=username,
                             rolename=rolename, password='admin',
                             name='{} User'.format(username),
                             email='{}@user.com'.format(username))

        pass_hash = password_hash('admin', user['password'])
        self.assertDictEqual(user, {
            'username': username,
            'password': pass_hash,
            'name': '{} User'.format(username),
            'email': '{}@user.com'.format(username),
            'roles': [rolename] if rolename else []
        })
        self.validate_persistent_user(username, [rolename] if rolename else [],
                                      pass_hash, '{} User'.format(username),
                                      '{}@user.com'.format(username))

    def test_create_user_with_role(self):
        self.test_add_role_scope_perms()
        self.test_create_user(rolename='test_role')

    def test_create_user_with_system_role(self):
        self.test_create_user(rolename='administrator')

    def test_delete_user(self):
        self.test_create_user()
        out = self.exec_cmd('ac-user-delete', username='admin')
        self.assertEqual(out, "User 'admin' deleted")
        users = self.exec_cmd('ac-user-show')
        self.assertEqual(len(users), 0)
        self.validate_persistent_no_user('admin')

    def test_create_duplicate_user(self):
        self.test_create_user()

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-create', username='admin', password='admin')

        self.assertEqual(ctx.exception.retcode, -errno.EEXIST)
        self.assertEqual(str(ctx.exception), "User 'admin' already exists")

    def test_delete_nonexistent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-delete', username='admin')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_add_user_roles(self, username='admin',
                            roles=['pool-manager', 'block-manager']):
        self.test_create_user(username)
        uroles = []
        for role in roles:
            uroles.append(role)
            uroles.sort()
            user = self.exec_cmd('ac-user-add-roles', username=username,
                                 roles=[role])
            self.assertDictContainsSubset({'roles': uroles}, user)
        self.validate_persistent_user(username, uroles)

    def test_add_user_roles2(self):
        self.test_create_user()
        user = self.exec_cmd('ac-user-add-roles', username="admin",
                             roles=['pool-manager', 'block-manager'])
        self.assertDictContainsSubset(
            {'roles': ['block-manager', 'pool-manager']}, user)
        self.validate_persistent_user('admin', ['block-manager',
                                                'pool-manager'])

    def test_add_user_roles_not_existent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-add-roles', username="admin",
                          roles=['pool-manager', 'block-manager'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_add_user_roles_not_existent_role(self):
        self.test_create_user()
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-add-roles', username="admin",
                          roles=['Invalid Role'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception),
                         "Role 'Invalid Role' does not exist")

    def test_set_user_roles(self):
        self.test_create_user()
        user = self.exec_cmd('ac-user-add-roles', username="admin",
                             roles=['pool-manager'])
        self.assertDictContainsSubset(
            {'roles': ['pool-manager']}, user)
        self.validate_persistent_user('admin', ['pool-manager'])
        user = self.exec_cmd('ac-user-set-roles', username="admin",
                             roles=['rgw-manager', 'block-manager'])
        self.assertDictContainsSubset(
            {'roles': ['block-manager', 'rgw-manager']}, user)
        self.validate_persistent_user('admin', ['block-manager',
                                                'rgw-manager'])

    def test_set_user_roles_not_existent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-set-roles', username="admin",
                          roles=['pool-manager', 'block-manager'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_set_user_roles_not_existent_role(self):
        self.test_create_user()
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-set-roles', username="admin",
                          roles=['Invalid Role'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception),
                         "Role 'Invalid Role' does not exist")

    def test_del_user_roles(self):
        self.test_add_user_roles()
        user = self.exec_cmd('ac-user-del-roles', username="admin",
                             roles=['pool-manager'])
        self.assertDictContainsSubset(
            {'roles': ['block-manager']}, user)
        self.validate_persistent_user('admin', ['block-manager'])

    def test_del_user_roles_not_existent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-del-roles', username="admin",
                          roles=['pool-manager', 'block-manager'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_del_user_roles_not_existent_role(self):
        self.test_create_user()
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-del-roles', username="admin",
                          roles=['Invalid Role'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception),
                         "Role 'Invalid Role' does not exist")

    def test_del_user_roles_not_associated_role(self):
        self.test_create_user()
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-del-roles', username="admin",
                          roles=['rgw-manager'])

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception),
                         "Role 'rgw-manager' is not associated with user "
                         "'admin'")

    def test_show_user(self):
        self.test_add_user_roles()
        user = self.exec_cmd('ac-user-show', username='admin')
        pass_hash = password_hash('admin', user['password'])
        self.assertDictEqual(user, {
            'username': 'admin',
            'password': pass_hash,
            'name': 'admin User',
            'email': 'admin@user.com',
            'roles': ['block-manager', 'pool-manager']
        })

    def test_show_nonexistent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-show', username='admin')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_show_all_users(self):
        self.test_add_user_roles('admin', ['administrator'])
        self.test_add_user_roles('guest', ['read-only'])
        users = self.exec_cmd('ac-user-show')
        self.assertEqual(len(users), 2)
        for user in users:
            self.assertIn(user, ['admin', 'guest'])

    def test_del_role_associated_with_user(self):
        self.test_create_role()
        self.test_add_user_roles('guest', ['test_role'])

        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-role-delete', rolename='test_role')

        self.assertEqual(ctx.exception.retcode, -errno.EPERM)
        self.assertEqual(str(ctx.exception),
                         "Role 'test_role' is still associated with user "
                         "'guest'")

    def test_set_user_info(self):
        self.test_create_user()
        user = self.exec_cmd('ac-user-set-info', username='admin',
                             name='Admin Name', email='admin@admin.com')
        pass_hash = password_hash('admin', user['password'])
        self.assertDictEqual(user, {
            'username': 'admin',
            'password': pass_hash,
            'name': 'Admin Name',
            'email': 'admin@admin.com',
            'roles': []
        })
        self.validate_persistent_user('admin', [], pass_hash, 'Admin Name',
                                      'admin@admin.com')

    def test_set_user_info_nonexistent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-set-info', username='admin',
                          name='Admin Name', email='admin@admin.com')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_set_user_password(self):
        self.test_create_user()
        user = self.exec_cmd('ac-user-set-password', username='admin',
                             password='newpass')
        pass_hash = password_hash('newpass', user['password'])
        self.assertDictEqual(user, {
            'username': 'admin',
            'password': pass_hash,
            'name': 'admin User',
            'email': 'admin@user.com',
            'roles': []
        })
        self.validate_persistent_user('admin', [], pass_hash, 'admin User',
                                      'admin@user.com')

    def test_set_user_password_nonexistent_user(self):
        with self.assertRaises(CmdException) as ctx:
            self.exec_cmd('ac-user-set-password', username='admin',
                          password='newpass')

        self.assertEqual(ctx.exception.retcode, -errno.ENOENT)
        self.assertEqual(str(ctx.exception), "User 'admin' does not exist")

    def test_set_login_credentials(self):
        self.exec_cmd('set-login-credentials', username='admin',
                      password='admin')
        user = self.exec_cmd('ac-user-show', username='admin')
        pass_hash = password_hash('admin', user['password'])
        self.assertDictEqual(user, {
            'username': 'admin',
            'password': pass_hash,
            'name': None,
            'email': None,
            'roles': ['administrator']
        })
        self.validate_persistent_user('admin', ['administrator'], pass_hash,
                                      None, None)

    def test_set_login_credentials_for_existing_user(self):
        self.test_add_user_roles('admin', ['read-only'])
        self.exec_cmd('set-login-credentials', username='admin',
                      password='admin2')
        user = self.exec_cmd('ac-user-show', username='admin')
        pass_hash = password_hash('admin2', user['password'])
        self.assertDictEqual(user, {
            'username': 'admin',
            'password': pass_hash,
            'name': 'admin User',
            'email': 'admin@user.com',
            'roles': ['read-only']
        })
        self.validate_persistent_user('admin', ['read-only'], pass_hash,
                                      'admin User', 'admin@user.com')

    def test_load_v1(self):
        self.CONFIG_KEY_DICT['accessdb_v1'] = '''
            {{
                "users": {{
                    "admin": {{
                        "username": "admin",
                        "password":
                "$2b$12$sd0Az7mm3FaJl8kN3b/xwOuztaN0sWUwC1SJqjM4wcDw/s5cmGbLK",
                        "roles": ["block-manager", "test_role"],
                        "name": "admin User",
                        "email": "admin@user.com"
                    }}
                }},
                "roles": {{
                    "test_role": {{
                        "name": "test_role",
                        "description": "Test Role",
                        "scopes_permissions": {{
                            "{}": ["{}", "{}"],
                            "{}": ["{}"]
                        }}
                    }}
                }},
                "version": 1
            }}
        '''.format(Scope.ISCSI, Permission.READ, Permission.UPDATE,
                   Scope.POOL, Permission.CREATE)

        load_access_control_db()
        role = self.exec_cmd('ac-role-show', rolename="test_role")
        self.assertDictEqual(role, {
            'name': 'test_role',
            'description': "Test Role",
            'scopes_permissions': {
                Scope.ISCSI: [Permission.READ, Permission.UPDATE],
                Scope.POOL: [Permission.CREATE]
            }
        })
        user = self.exec_cmd('ac-user-show', username="admin")
        self.assertDictEqual(user, {
            'username': 'admin',
            'password':
                "$2b$12$sd0Az7mm3FaJl8kN3b/xwOuztaN0sWUwC1SJqjM4wcDw/s5cmGbLK",
            'name': 'admin User',
            'email': 'admin@user.com',
            'roles': ['block-manager', 'test_role']
        })

    def test_update_from_previous_version_v1(self):
        self.CONFIG_KEY_DICT['username'] = 'admin'
        self.CONFIG_KEY_DICT['password'] = \
            '$2b$12$sd0Az7mm3FaJl8kN3b/xwOuztaN0sWUwC1SJqjM4wcDw/s5cmGbLK'
        load_access_control_db()
        user = self.exec_cmd('ac-user-show', username="admin")
        self.assertDictEqual(user, {
            'username': 'admin',
            'password':
                "$2b$12$sd0Az7mm3FaJl8kN3b/xwOuztaN0sWUwC1SJqjM4wcDw/s5cmGbLK",
            'name': None,
            'email': None,
            'roles': ['administrator']
        })
