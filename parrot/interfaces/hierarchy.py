"""Utilities for managing the employee hierarchy stored in ArangoDB."""
from __future__ import annotations
import asyncio
from typing import List, Dict, Optional, Any, TypeVar, ParamSpec
import logging
from dataclasses import dataclass
from xmlrpc import client
# from arango import ArangoClient
from arangoasync import ArangoClient
from arangoasync.auth import Auth
from asyncdb import AsyncDB
from ..conf import default_dsn, EMPLOYEES_TABLE
from ..memory.cache import CacheMixin, cached_query

P = ParamSpec('P')
T = TypeVar('T')


logging.getLogger('arangoasync').setLevel(logging.WARNING)


@dataclass
class Employee:
    """Employee Information"""
    employee_id: str
    associate_oid: str
    first_name: str
    last_name: str
    display_name: str
    email: str
    job_code: str
    position_id: str
    department: str
    program: str
    reports_to: Optional[str]

class EmployeeHierarchyManager(CacheMixin):
    """
    Hierarchy Manager using ArangoDB to store employees and their reporting structure.
    It supports importing from PostgreSQL, inserting individual employees,
    and performing hierarchical queries like finding superiors, subordinates, and colleagues.

    Attributes:
        arango_host (str): Hostname for ArangoDB server.
        arango_port (int): Port for ArangoDB server.
        db_name (str): Name of the ArangoDB database to use.
        username (str): Username for ArangoDB authentication.
        password (str): Password for ArangoDB authentication.
        employees_collection (str): Name of the collection for employee vertices.
    """

    def __init__(
        self,
        arango_host='localhost',
        arango_port=8529,
        db_name='company_db',
        username='root',
        password='',
        **kwargs
    ):
        super().__init__(**kwargs)
        # ArangoDB connection
        self.client = ArangoClient(
            hosts=f'http://{arango_host}:{arango_port}'
        )
        self.auth = Auth(
            username=username,
            password=password
        )
        self._username = username
        self._password = password
        self._database = db_name
        self.sys_db = None
        self.db = None
        # Nombres de colecciones
        self.employees_collection = kwargs.get('employees_collection', 'employees')
        self.reports_to_collection = kwargs.get('reports_to_collection', 'reports_to')
        self.graph_name = kwargs.get('graph_name', 'org_hierarchy')
        self._primary_key = kwargs.get('primary_key', 'employee_id')

        # postgreSQL connection:
        self.pg_client = AsyncDB('pg', dsn=default_dsn)
        # postgreSQL employees table:
        self.employees_table = kwargs.get(
            'pg_employees_table',
            EMPLOYEES_TABLE
        )

    async def __aenter__(self):
        await self.connection()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self.client:
            try:
                await self.client.close()
            except Exception as e:
                print(f"Error closing ArangoDB client: {e}")

    async def connection(self):
        """
        Async context manager for ArangoDB connection
        """
        # Connect to "_system" database as root user.
        self.sys_db = await self.client.db("_system", auth=self.auth)
        if not await self.sys_db.has_database(self._database):
            await self.sys_db.create_database(self._database)

        # Connect To database:
        self.db = await self.client.db(self._database, auth=self.auth)
        return self.db

    async def _setup_collections(self):
        """
        Creates the Collection and Graph structure in ArangoDB if they do not exist.
        """
        # 1. Create Employees collection (vertices)
        if not await self.db.has_collection(self.employees_collection):
            await self.db.create_collection(self.employees_collection)
            print(f"✓ Collection '{self.employees_collection}' created")

        # 2. Create ReportsTo collection (edges)
        if not await self.db.has_collection(self.reports_to_collection):
            await self.db.create_collection(self.reports_to_collection, edge=True)
            print(f"✓ Collection of edges '{self.reports_to_collection}' created")

        # 3. Create the graph
        if not await self.db.has_graph(self.graph_name):
            graph = await self.db.create_graph(self.graph_name)

            # Define Graph Edge Definitions
            await graph.create_edge_definition(
                edge_collection=self.reports_to_collection,
                from_vertex_collections=[self.employees_collection],
                to_vertex_collections=[self.employees_collection]
            )
            print(f"✓ Graph '{self.graph_name}' created")

        # 4. Create indexes to optimize searches
        employees = self.db.collection(self.employees_collection)
        await self._ensure_index(employees, [self._primary_key], unique=True)
        await self._ensure_index(employees, ['department', 'program'], unique=False)
        await self._ensure_index(employees, ['position_id'], unique=False)
        await self._ensure_index(employees, ['associate_oid'], unique=False)

    async def _ensure_index(self, collection, fields: List[str], unique: bool = False):
        """
        Ensures an index exists. If it doesn't, creates it.
        If it exists but with different properties, drops and recreates it.

        Args:
            collection: The ArangoDB collection
            fields: List of field names for the index
            unique: Whether the index should be unique
        """
        existing_indexes = await collection.indexes()

        # Check if an index with these exact fields already exists
        for idx in existing_indexes:
            # Skip the primary index (_key)
            if idx['type'] == 'primary':
                continue

            # Check if this index has the same fields
            if idx['fields'] == fields:
                # Check if uniqueness matches
                if idx.get('unique', False) == unique:
                    print(f"✓ Index on {fields} already exists")
                    return
                else:
                    # Index exists but with different uniqueness - drop it
                    print(f"⚠ Dropping existing index on {fields} (uniqueness mismatch)")
                    try:
                        await collection.delete_index(idx['id'])
                    except Exception as e:
                        print(f"Warning: Could not drop index {idx['id']}: {e}")
                    break

        # Create an index:
        try:
            await collection.add_index(
                type="persistent",
                fields=fields,
                options={"unique": unique}
            )
        except Exception as e:
            print(f"⚠ Could not create persistent index on {fields}: {e}")

        # Create a hash index
        try:
            await collection.add_hash_index(fields=fields, unique=unique)
            unique_str = "unique " if unique else ""
            print(f"✓ {unique_str}Index on {fields} created")
        except Exception as e:
            print(f"⚠ Could not create index on {fields}: {e}")

    async def drop_all_indexes(self):
        """
        Drop all user-defined indexes from the employees collection.
        Useful for troubleshooting or resetting the collection.
        """
        employees = self.db.collection(self.employees_collection)
        existing_indexes = await employees.indexes()

        dropped_count = 0
        for idx in existing_indexes:
            # Skip the primary index (_key) - it cannot be dropped
            if idx['type'] == 'primary':
                continue

            try:
                await employees.delete_index(idx['id'])
                print(f"✓ Dropped index: {idx['fields']}")
                dropped_count += 1
            except Exception as e:
                print(f"⚠ Could not drop index {idx['id']}: {e}")

        print(f"✓ Dropped {dropped_count} indexes")
        return dropped_count

    async def import_from_postgres(self):
        """
        Import employees from PostgreSQL

        Args:
            pg_conn_string: Connection string for PostgreSQL
            e.g. "dbname=mydb user=user password=pass host=localhost"
        """
        query = f"""
SELECT
    associate_id as employee_id,
    associate_oid,
    first_name,
    last_name,
    display_name,
    job_code,
    position_id,
    corporate_email as email,
    department,
    reports_to_associate_id as reports_to,
    region as program
FROM {self.employees_table}
WHERE status = 'Active'
ORDER BY reports_to_associate_id NULLS FIRST
        """
        async with await self.pg_client.connection() as conn:  # pylint: disable=E1101 # noqa
            employees_data = await conn.fetchall(query)

        # cleanup collection before import
        await self.truncate_hierarchy()

        employees_collection = self.db.collection(self.employees_collection)
        reports_to_collection = self.db.collection(self.reports_to_collection)

        # Mapping Associate OID to ArangoDB _id
        oid_to_id = {}
        # First Step: insert employees
        for row in employees_data:
            # Clean whitespace from IDs
            _id = row.get(self._primary_key, 'employee_id').strip()
            if isinstance(_id, str):
                _id = _id.strip()

            reports_to = row['reports_to']
            if isinstance(reports_to, str):
                reports_to = reports_to.strip() if reports_to else None

            employee_doc = {
                '_key': _id,  # Employee_id is the primary key
                self._primary_key: _id,
                'associate_oid': row['associate_oid'],
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'display_name': row['display_name'],
                'email': row['email'],
                'job_code': row['job_code'],
                'position_id': row['position_id'],
                'department': row['department'],
                'program': row['program'],
                'reports_to': reports_to
            }

            result = await employees_collection.insert(
                employee_doc,
                overwrite=True
            )
            oid_to_id[_id] = result['_id']

        print(f"✓ {len(employees_data)} Employees inserted")

        # Second pass: create edges (reports_to relationships)
        edges_created = 0
        skipped_edges = 0
        missing_bosses = set()

        for row in employees_data:
            # Clean whitespace from IDs (consistent with first pass)
            _id = row.get(self._primary_key, 'employee_id').strip()
            if isinstance(_id, str):
                _id = _id.strip()

            reports_to = row['reports_to']
            if isinstance(reports_to, str):
                reports_to = reports_to.strip() if reports_to else None

            if reports_to:  # If has a boss
                # Verify that the boss exists in the database
                if reports_to not in oid_to_id:
                    skipped_edges += 1
                    missing_bosses.add(reports_to)
                    continue

                edge_doc = {
                    '_from': oid_to_id[_id],  # Employee
                    '_to': oid_to_id[reports_to],  # His boss
                }

                await reports_to_collection.insert(edge_doc)
                edges_created += 1

        print(f"✓ {edges_created} 'reports_to' edges created")
        print(
            f"✓ {await self.db.collection(name=self.reports_to_collection).count()} total 'reports_to' edges"
        )

        if skipped_edges > 0:
            print(f"⚠ {skipped_edges} edges skipped (boss not found)")
            print(f"⚠ Missing boss IDs: {missing_bosses}")

        # Setup collections and graph
        await self._setup_collections()

    async def truncate_hierarchy(self) -> None:
        """
        Truncate employees and reports_to collections.

        This:
        - Deletes all employee vertices.
        - Deletes all reports_to edges.
        - Keeps:
            - Collections
            - Indexes
            - Graph definition

        Use this when you want a clean reload from PostgreSQL.
        """
        # Truncate edges first (good practice to avoid dangling edges mid-operation)
        if await self.db.has_collection(self.reports_to_collection):
            edges = self.db.collection(self.reports_to_collection)
            await edges.truncate()

        if await self.db.has_collection(self.employees_collection):
            employees = self.db.collection(self.employees_collection)
            await employees.truncate()

        print("✓ Hierarchy data truncated (employees + reports_to)")


    async def insert_employee(self, employee: Employee) -> str:
        """
        Insert an individual employee
        """
        employees_collection = self.db.collection(name=self.employees_collection)
        reports_to_collection = self.db.collection(name=self.reports_to_collection)

        # Insert employee
        employee_doc = {
            '_key': employee.employee_id,
            self._primary_key: employee.employee_id,
            'associate_oid': employee.associate_oid,
            'first_name': employee.first_name,
            'last_name': employee.last_name,
            'display_name': employee.display_name,
            'email': employee.email,
            'job_code': employee.job_code,
            'position_id': employee.position_id,
            'department': employee.department,
            'program': employee.program,
            'reports_to': employee.reports_to
        }

        result = await employees_collection.insert(employee_doc, overwrite=True)
        employee_id = result['_id']

        # Crear arista si reporta a alguien
        if employee.reports_to:
            boss_id = f"{self.employees_collection}/{employee.reports_to}"

            edge_doc = {
                '_from': employee_id,
                '_to': boss_id
            }

            await reports_to_collection.insert(edge_doc)

        return employee_id

    # ============= Hierarchical Queries =============
    # @cached_query("does_report_to", ttl=3600)
    async def does_report_to(self, employee_oid: str, boss_oid: str, limit: int = 1) -> bool:
        """
        Check if employee_oid reports directly or indirectly to boss_oid.

        Args:
            employee_oid: Associate OID of the employee
            boss_oid: Associate OID of the boss

        Returns:
            True if employee reports to boss, False otherwise
        """
        query = """
        FOR v, e, p IN 1..10 OUTBOUND
            CONCAT(@collection, '/', @employee_oid)
            GRAPH @graph_name
            FILTER v.employee_id == @boss_oid
            LIMIT @limit
            RETURN true
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'boss_oid': boss_oid,
                'graph_name': self.graph_name,
                'limit': limit
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return len(results) > 0

    # @cached_query("get_all_superiors", ttl=3600)
    async def get_all_superiors(self, employee_oid: str) -> List[Dict]:
        """
        Return all superiors of an employee up to the CEO.

        Returns:
            List ordered from direct boss to CEO
        """
        query = """
FOR v, e, p IN 1..10 OUTBOUND
    CONCAT(@collection, '/', @employee_oid)
    GRAPH @graph_name
    RETURN {
        employee_id: v.employee_id,
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program,
        level: LENGTH(p.edges)
    }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    @cached_query("get_direct_reports", ttl=3600)
    async def get_direct_reports(self, boss_oid: str) -> List[Dict]:
        """
        Return direct reports of a boss
        """
        query = """
FOR v, e, p IN 1..1 INBOUND
    CONCAT(@collection, '/', @boss_oid)
    GRAPH @graph_name
    RETURN {
        employee_id: v.employee_id,
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program
    }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'boss_oid': boss_oid,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    # @cached_query("get_all_subordinates", ttl=3600)
    async def get_all_subordinates(self, boss_oid: str, max_depth: int = 10) -> List[Dict]:
        """
        Return all subordinates (direct and indirect) of a boss
        """
        query = """
FOR v, e, p IN 1..@max_depth INBOUND
    CONCAT(@collection, '/', @boss_oid)
    GRAPH @graph_name
    RETURN {
        employee_id: v.employee_id,
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program,
        level: LENGTH(p.edges)
    }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'boss_oid': boss_oid,
                'max_depth': max_depth,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results

    # @cached_query("get_org_chart", ttl=3600)
    async def get_org_chart(self, root_oid: Optional[str] = None) -> Dict:
        """
        Build the complete org chart as a hierarchical tree

        Args:
            root_oid: If specified, builds the tree from that node
            If None, searches for the CEO (node without boss)

        Returns:
            Hierarchical tree as a list of dictionaries
        """
        # If no root is specified, search for the CEO
        if root_oid is None:
            query_ceo = """
            FOR emp IN @@collection
                FILTER LENGTH(FOR v IN 1..1 OUTBOUND emp._id GRAPH @graph_name RETURN 1) == 0
                LIMIT 1
                RETURN emp.employee_id
            """
            cursor = await self.db.aql.execute(
                query_ceo,
                bind_vars={
                    '@collection': self.employees_collection,
                    'graph_name': self.graph_name
                }
            )
            async with cursor:
                results = [doc async for doc in cursor]
            if results:
                root_oid = results[0]
            else:
                return {}
        # Build the tree from the root_oid recursively
        query = """
        FOR v, e, p IN 0..10 INBOUND
            CONCAT(@collection, '/', @root_oid)
            GRAPH @graph_name
            RETURN {
                employee_id: v.employee_id,
                associate_oid: v.associate_oid,
                display_name: v.display_name,
                department: v.department,
                program: v.program,
                level: LENGTH(p.edges),
                path: p.vertices[*].employee_id
            }
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'root_oid': root_oid,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]

        return results

    @cached_query("get_colleagues", ttl=3600)
    async def get_colleagues(self, employee_oid: str) -> List[Dict[str, Any]]:
        """
        Return colleagues (employees who share the same boss)

        Args:
            employee_oid: Associate OID of the employee

        Returns:
            List of colleagues
        """
        query = """
        FOR boss IN 1..1 OUTBOUND
            CONCAT(@collection, '/', @employee_oid)
            GRAPH @graph_name

            FOR colleague IN 1..1 INBOUND
                boss._id
                GRAPH @graph_name
                FILTER colleague.employee_id != @employee_oid
                RETURN {
                    employee_id: colleague.employee_id,
                    associate_oid: colleague.associate_oid,
                    display_name: colleague.display_name,
                    department: colleague.department,
                    program: colleague.program
                }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]

        return results

    @cached_query("get_employee_info", ttl=7200)  # Cache por 2 horas
    async def get_employee_info(self, employee_oid: str) -> Optional[Dict]:
        """
        Get detailed information about an employee.

        Args:
            employee_oid: Employee ID (associate_oid)

        Returns:
            Dict with employee information or None if not found
            {

                'employee_id': str,
                'associate_oid': str,
                'display_name': str,
                'first_name': str,
                'last_name': str,
                'email': str,
                'department': str,
                'program': str,
                'position_id': str,
                'job_code': str
            }

        Example:
        ```python
        manager = EmployeeHierarchyManager(...)

        # First call - query ArangoDB
        info = await manager.get_employee_info('E003')

        # Second call - from Redis cache
        info = await manager.get_employee_info('E003')  # ⚡
        ```
        """
        query = """
        FOR emp IN @@collection
            FILTER emp.employee_id == @employee_oid
            LIMIT 1
            RETURN {
                employee_id: emp.employee_id,
                associate_oid: emp.associate_oid,
                display_name: emp.display_name,
                first_name: emp.first_name,
                last_name: emp.last_name,
                email: emp.email,
                department: emp.department,
                program: emp.program,
                position_id: emp.position_id,
                job_code: emp.job_code
            }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                '@collection': self.employees_collection,
                'employee_oid': employee_oid
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]

        return results[0] if results else None

    async def get_department_context(self, employee_oid: str) -> Dict:
        """
        Get a summary of the employee's department context, including
        superiors, colleagues, direct reports, and all subordinates.
        """
        # 1. Get employee info (async)
        employee_info = await self.get_employee_info(employee_oid)

        if not employee_info:
            # Employee not found
            return {
                'employee': {'employee_id': employee_oid},
                'reports_to_chain': [],
                'colleagues': [],
                'manages': [],
                'all_subordinates': [],
                'department': 'Unknown',
                'program': 'Unknown',
                'total_subordinates': 0,
                'direct_reports_count': 0,
                'colleagues_count': 0,
                'reporting_levels': 0
            }

        # 2. Get superiors (async)
        superiors = await self.get_all_superiors(employee_oid)

        # 3. Get colleagues (async)
        colleagues = await self.get_colleagues(employee_oid)

        # 4. Get direct reports (async)
        direct_reports = await self.get_direct_reports(employee_oid)

        # 5. Get all subordinates (async)
        all_subordinates = await self.get_all_subordinates(employee_oid)

        return {
            'employee': {
                'employee_id': employee_info['employee_id'],
                'associate_oid': employee_info['associate_oid'],
                'display_name': employee_info['display_name'],
                'email': employee_info.get('email'),
                'position_id': employee_info.get('position_id')
            },

            'reports_to_chain': [
                f"{s['display_name']} ({s['department']} - {s['program']})"
                for s in superiors
            ],

            'colleagues': [c['display_name'] for c in colleagues],
            'manages': [r['display_name'] for r in direct_reports],
            'all_subordinates': all_subordinates,

            # Usar department/program del empleado directamente
            'department': employee_info['department'],
            'program': employee_info['program'],

            # Stats
            'total_subordinates': len(all_subordinates),
            'direct_reports_count': len(direct_reports),
            'colleagues_count': len(colleagues),
            'reporting_levels': len(superiors)
        }

    async def are_in_same_department(self, employee1: str, employee2: str) -> bool:
        """
        Check if two employees are in the same department (broader than colleagues).

        Args:
            employee1: First employee's ID
            employee2: Second employee's ID

        Returns:
            True if in same department, False otherwise
        """
        query = """
        LET emp1 = DOCUMENT(CONCAT(@collection, '/emp_', @emp1))
        LET emp2 = DOCUMENT(CONCAT(@collection, '/emp_', @emp2))

        RETURN {
            same_department: emp1.department == emp2.department,
            same_program: emp1.program == emp2.program,
            employee1: {
                name: emp1.display_name,
                department: emp1.department,
                program: emp1.program
            },
            employee2: {
                name: emp2.display_name,
                department: emp2.department,
                program: emp2.program
            }
        }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'emp1': employee1,
                'emp2': employee2
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        result = results[0] if results else {}
        return result.get('same_department', False)

    async def get_team_members(
        self,
        manager_id: str,
        include_all_levels: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all team members under a manager.

        Args:
            manager_id: Manager's ID
            include_all_levels: If True, include all subordinates recursively.
                            If False, only direct reports.

        Returns:
            List of team member information
        """
        depth = "1..99" if include_all_levels else "1..1"

        query = f"""
        FOR member, e, p IN {depth} INBOUND CONCAT(@collection, '/emp_', @manager_id)
            GRAPH @graph_name
            RETURN {{
                employee_id: member.employee_id,
                display_name: member.display_name,
                department: member.department,
                program: member.program,
                associate_oid: member.associate_oid,
                level: LENGTH(p.edges),
                reports_directly: LENGTH(p.edges) == 1
            }}
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'manager_id': manager_id,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]

        return results

    async def are_colleagues(self, employee1: str, employee2: str) -> bool:
        """
        Check if two employees are colleagues (same boss, same level).

        Two employees are considered colleagues if:
        1. They have the same direct manager
        2. They are at the same hierarchical level
        3. They are not the same person

        Args:
            employee1: First employee's ID
            employee2: Second employee's ID

        Returns:
            True if they are colleagues, False otherwise
        """
        if employee1 == employee2:
            return False  # Same person cannot be their own colleague

        # Method 1: Check if they have the same direct boss
        query = """
    // Find the direct boss of employee1
    LET boss1 = (
        FOR v IN 1..1 OUTBOUND CONCAT(@collection, '/', @emp1)
            GRAPH @graph_name
            RETURN v._key
    )

    // Find the direct boss of employee2
    LET boss2 = (
        FOR v IN 1..1 OUTBOUND CONCAT(@collection, '/', @emp2)
            GRAPH @graph_name
            RETURN v._key
    )

    // Check if they have the same boss
    RETURN {
        employee1_boss: boss1[0],
        employee2_boss: boss2[0],
        same_boss: boss1[0] == boss2[0] AND boss1[0] != null,
        are_colleagues: boss1[0] == boss2[0] AND boss1[0] != null
    }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'emp1': employee1,
                'emp2': employee2,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        result = results[0] if results else {}
        return result.get('are_colleagues', False)

    async def is_manager(self, employee_oid: str) -> bool:
        """
        Check if the given employee is a manager (has direct reports).

        Args:
            employee_oid: Employee ID to check

        Returns:
            True if the employee is a manager, False otherwise
        """
        query = """
        FOR v IN 1..1 INBOUND
            CONCAT(@collection, '/', @employee_oid)
            GRAPH @graph_name
            LIMIT 1
            RETURN true
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return len(results) > 0

    async def get_closest_common_boss(self, employee1: str, employee2: str) -> Optional[Dict]:
        """
        Find the closest common boss between two employees.

        Args:
            employee1: First employee's ID
            employee2: Second employee's ID

        Returns:
            Dict with common boss information or None if not found
        """
        query = """
        LET paths1 = (
            FOR v, e, p IN 1..10 OUTBOUND
                CONCAT(@collection, '/', @employee1)
                GRAPH @graph_name
                RETURN {boss: v, path: p}
        )

        LET paths2 = (
            FOR v, e, p IN 1..10 OUTBOUND
                CONCAT(@collection, '/', @employee2)
                GRAPH @graph_name
                RETURN {boss: v, path: p}
        )

        FOR p1 IN paths1
            FOR p2 IN paths2
                FILTER p1.boss._key == p2.boss._key
                SORT LENGTH(p1.path.edges) + LENGTH(p2.path.edges) ASC
                LIMIT 1
                RETURN {
                    employee_id: p1.boss.employee_id,
                    associate_oid: p1.boss.associate_oid,
                    display_name: p1.boss.display_name,
                    department: p1.boss.department,
                    program: p1.boss.program
                }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee1': employee1,
                'employee2': employee2,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
        return results[0] if results else None

    async def is_boss_of(
        self,
        employee_oid: str,
        boss_oid: str,
        direct_only: bool = False
    ) -> Dict[str, Any]:
        """
        Check if boss_oid is a boss (direct or indirect) of employee_oid.

        Args:
            employee_oid: Employee's ID
            boss_oid: Boss's ID
            direct_only: If True, check only direct reporting (level 1)
                    If False, check any level in hierarchy

        Returns:
            Dict with relationship details:
            {
                'is_manager': bool,
                'is_direct_manager': bool,
                'level': int (0 if not manager, 1 for direct, 2+ for indirect),
                'path': list of employee IDs from employee to manager
            }
        """
        if employee_oid == boss_oid:
            return {
                'is_manager': False,
                'is_direct_manager': False,
                'level': 0,
                'path': [],
                'relationship': 'same_person'
            }

        depth = "1..1" if direct_only else "1..99"

        query = f"""
// Find path from employee to potential manager
FOR v, e, p IN {depth} OUTBOUND CONCAT(@collection, '/', @employee_oid)
    GRAPH @graph_name
    FILTER v._key == @boss_oid OR v.employee_id == @boss_oid
    LIMIT 1
    RETURN {{
        found: true,
        level: LENGTH(p.edges),
        path: p.vertices[*].employee_id,
        manager_name: v.display_name,
        employee_name: DOCUMENT(CONCAT(@collection, '/', @employee_oid)).display_name
    }}
        """
        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'boss_oid': boss_oid,
                'graph_name': self.graph_name
            }
        )
        async with cursor:
            results = [doc async for doc in cursor]
            if not results:
                return {
                    'is_manager': False,
                    'is_direct_manager': False,
                    'level': 0,
                    'path': [],
                    'relationship': 'not_manager'
                }
            result = results[0]
            level = result['level']
            return {
                'is_manager': True,
                'is_direct_manager': level == 1,
                'level': level,
                'path': result['path'],
                'relationship': 'direct_manager' if level == 1 else f'manager_level_{level}',
                'manager_name': result['manager_name'],
                'employee_name': result['employee_name']
            }

    async def is_subordinate(
        self,
        employee_oid: str,
        manager_oid: str,
        direct_only: bool = False
    ) -> Dict[str, Any]:
        """
        Check if employee_oid is a subordinate of manager_oid.
        This is the inverse of is_boss_of().

        Args:
            employee_oid: Employee's ID
            manager_oid: Potential manager's ID
            direct_only: If True, check only direct reporting

        Returns:
            Dict with relationship details
        """
        # This is just the inverse of is_boss_of
        return await self.is_boss_of(employee_oid, manager_oid, direct_only)

    async def get_relationship(
        self,
        employee1: str,
        employee2: str
    ) -> Dict[str, Any]:
        """
        Get the complete relationship between two employees.

        Args:
            employee1: First employee's ID
            employee2: Second employee's ID

        Returns:
            Comprehensive relationship information
        """
        if employee1 == employee2:
            return {
                'relationship': 'same_person',
                'employee1_id': employee1,
                'employee2_id': employee2
            }

        # Check all possible relationships in parallel
        results = await asyncio.gather(
            self.is_boss_of(employee1, employee2),
            self.is_boss_of(employee2, employee1),
            self.are_colleagues(employee1, employee2),
            self.are_in_same_department(employee1, employee2),
            return_exceptions=True
        )

        emp1_manages_emp2 = {'is_manager': False} if isinstance(results[0], Exception) else results[0]
        emp2_manages_emp1 = {'is_manager': False} if isinstance(results[1], Exception) else results[1]
        are_colleagues = False if isinstance(results[2], Exception) else results[2]
        same_department = False if isinstance(results[3], Exception) else results[3]

        # Determine primary relationship
        if emp1_manages_emp2['is_manager']:
            primary = 'manager_subordinate'
            details = {
                'manager': employee1,
                'subordinate': employee2,
                'level': emp1_manages_emp2['level'],
                'is_direct': emp1_manages_emp2['is_direct_manager']
            }
        elif emp2_manages_emp1['is_manager']:
            primary = 'subordinate_manager'
            details = {
                'manager': employee2,
                'subordinate': employee1,
                'level': emp2_manages_emp1['level'],
                'is_direct': emp2_manages_emp1['is_direct_manager']
            }
        elif are_colleagues:
            primary = 'colleagues'
            details = {'same_boss': True}
        elif same_department:
            primary = 'same_department'
            details = {'department_colleagues': True}
        else:
            primary = 'no_direct_relationship'
            details = {}

        return {
            'relationship': primary,
            'employee1_id': employee1,
            'employee2_id': employee2,
            'details': details,
            'are_colleagues': are_colleagues,
            'same_department': same_department,
            'emp1_manages_emp2': emp1_manages_emp2['is_manager'],
            'emp2_manages_emp1': emp2_manages_emp1['is_manager']
        }

    async def check_management_chain(
        self,
        employee_id: str,
        target_manager_id: str
    ) -> Dict[str, Any]:
        """
        Check if target_manager_id is anywhere in employee's management chain.
        Returns the complete path and level if found.

        Args:
            employee_id: Employee's ID
            target_manager_id: Manager to search for in chain

        Returns:
            Dict with chain details
        """
        query = """
        // Get all managers in the chain
        FOR v, e, p IN 1..99 OUTBOUND CONCAT(@collection, '/', @employee_id)
            GRAPH @graph_name
            OPTIONS {bfs: false}  // Use DFS to get the path
            FILTER v._key == @target_manager OR v.employee_id == @target_manager
            LIMIT 1
            RETURN {
                found: true,
                level: LENGTH(p.edges),
                chain: (
                    FOR vertex IN p.vertices
                        RETURN {
                            id: vertex.employee_id,
                            name: vertex.display_name,
                            department: vertex.department
                        }
                )
            }
        """

        cursor = await self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_id': employee_id,
                'target_manager': target_manager_id,
                'graph_name': self.graph_name
            }
        )

        async with cursor:
            results = [doc async for doc in cursor]

        if results:
            return {
                'in_chain': True,
                **results[0]
            }
        else:
            return {
                'in_chain': False,
                'found': False,
                'level': 0,
                'chain': []
            }
