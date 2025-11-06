from typing import List, Dict, Optional, TypeVar, ParamSpec
from dataclasses import dataclass
from functools import wraps
import hashlib
from arango import ArangoClient
from asyncdb import AsyncDB
from ..conf import default_dsn
from ..memory.cache import CacheMixin, cached_query

P = ParamSpec('P')
T = TypeVar('T')


@dataclass
class Employee:
    """Employee Information"""
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
        self.sys_db = self.client.db(
            '_system',
            username=username,
            password=password
        )

        # Crear o conectar a la base de datos
        if not self.sys_db.has_database(db_name):
            self.sys_db.create_database(db_name)

        self.db = self.client.db(db_name, username=username, password=password)

        # Nombres de colecciones
        self.employees_collection = kwargs.get('employees_collection', 'employees')
        self.reports_to_collection = kwargs.get('reports_to_collection', 'reports_to')
        self.graph_name = kwargs.get('graph_name', 'org_hierarchy')
        self._primary_key = kwargs.get('primary_key', 'associate_oid')

        # postgreSQL connection:
        self.pg_client = AsyncDB('pg', dsn=default_dsn)
        # postgreSQL employees table:
        self.employees_table = kwargs.get('pg_employees_table', 'troc.employees')

        # Setup collections and graph
        self._setup_collections()

    def _setup_collections(self):
        """
        Crea las colecciones y el grafo si no existen
        """
        # 1. Create Employees collection (vertices)
        if not self.db.has_collection(self.employees_collection):
            self.db.create_collection(self.employees_collection)
            print(f"✓ Collection '{self.employees_collection}' created")

        # 2. Create ReportsTo collection (edges)
        if not self.db.has_collection(self.reports_to_collection):
            self.db.create_collection(self.reports_to_collection, edge=True)
            print(f"✓ Collection of edges '{self.reports_to_collection}' created")

        # 3. Create the graph
        if not self.db.has_graph(self.graph_name):
            graph = self.db.create_graph(self.graph_name)

            # Definir la estructura del grafo
            graph.create_edge_definition(
                edge_collection=self.reports_to_collection,
                from_vertex_collections=[self.employees_collection],
                to_vertex_collections=[self.employees_collection]
            )
            print(f"✓ Graph '{self.graph_name}' created")

        # 4. Create indexes to optimize searches
        employees = self.db.collection(self.employees_collection)

        # Index by associate_oid (business key)
        if all(idx['fields'] != [self._primary_key] for idx in employees.indexes()):
            employees.add_hash_index(fields=[self._primary_key], unique=True)
            print(f"✓ Index on '{self._primary_key}' created")

        # Index by department and program
        if all(idx['fields'] != ['department', 'program'] for idx in employees.indexes()):
            employees.add_hash_index(fields=['department', 'program'], unique=False)
            print("✓ Index on 'department' and 'program' created")

        # Index by position_id
        if all(idx['fields'] != ['position_id'] for idx in employees.indexes()):
            employees.add_hash_index(fields=['position_id'], unique=False)
            print("✓ Index on 'position_id' created")

    async def import_from_postgres(self):
        """
        Import employees from PostgreSQL

        Args:
            pg_conn_string: Connection string for PostgreSQL
            e.g. "dbname=mydb user=user password=pass host=localhost"
        """
        query = f"""
            SELECT
                associate_oid,
                first_name,
                last_name,
                display_name,
                job_code,
                position_id,
                corporate_email as email,
                department,
                reports_to_associate_oid as reports_to,
                region as program
            FROM {self.employees_table}
            ORDER BY reports_to_associate_oid NULLS FIRST
        """
        async with await self.pg_client.connection() as conn:  # pylint: disable=E1101 # noqa
            employees_data = await conn.fetchall(query)

        employees_collection = self.db.collection(self.employees_collection)
        reports_to_collection = self.db.collection(self.reports_to_collection)

        # Mapping Associate OID to ArangoDB _id
        oid_to_id = {}
        # First Step: insert employees
        for row in employees_data:
            _id = row.get(self._primary_key, 'associate_oid')
            reports_to = row['reports_to']
            employee_doc = {
                '_key': _id,  # Associate_oid is the primary key
                self._primary_key: _id,
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

            result = employees_collection.insert(employee_doc, overwrite=True)
            oid_to_id[_id] = result['_id']

        print(f"✓ {len(employees_data)} Employees inserted")

        # Second pass: create edges (reports_to relationships)
        edges_created = 0
        for row in employees_data:
            _id = row.get(self._primary_key, 'associate_oid')
            if reports_to := row['reports_to']:  # If has a boss
                edge_doc = {
                    '_from': oid_to_id[_id],  # Employee
                    '_to': oid_to_id[reports_to],  # His boss
                }

                reports_to_collection.insert(edge_doc)
                edges_created += 1

        print(f"✓ {edges_created} 'reports_to' edges created")

    def insert_employee(self, employee: Employee) -> str:
        """
        Insert an individual employee
        """
        employees_collection = self.db.collection(self.employees_collection)
        reports_to_collection = self.db.collection(self.reports_to_collection)

        # Insert employee
        employee_doc = {
            '_key': employee.associate_oid,  # Associate_oid is the primary key
            self._primary_key: employee.associate_oid,
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

        result = employees_collection.insert(employee_doc, overwrite=True)
        employee_id = result['_id']

        # Crear arista si reporta a alguien
        if employee.reports_to:
            boss_id = f"{self.employees_collection}/{employee.reports_to}"

            edge_doc = {
                '_from': employee_id,
                '_to': boss_id
            }

            reports_to_collection.insert(edge_doc)

        return employee_id

    # ============= Hierarchical Queries =============

    @cached_query("does_report_to", ttl=3600)
    def does_report_to(self, employee_oid: str, boss_oid: str) -> bool:
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
            FILTER v.associate_oid == @boss_oid
            LIMIT 1
            RETURN true
        """

        cursor = self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'boss_oid': boss_oid,
                'graph_name': self.graph_name
            }
        )

        results = list(cursor)
        return len(results) > 0

    @cached_query("get_all_superiors", ttl=3600)
    def get_all_superiors(self, employee_oid: str) -> List[Dict]:
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
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program,
        level: LENGTH(p.edges)
    }
        """
        cursor = self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'graph_name': self.graph_name
            }
        )
        return list(cursor)

    @cached_query("get_direct_reports", ttl=3600)
    def get_direct_reports(self, boss_oid: str) -> List[Dict]:
        """
        Return direct reports of a boss
        """
        query = """
FOR v, e, p IN 1..1 INBOUND
    CONCAT(@collection, '/', @boss_oid)
    GRAPH @graph_name
    RETURN {
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program
    }
        """

        cursor = self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'boss_oid': boss_oid,
                'graph_name': self.graph_name
            }
        )

        return list(cursor)

    @cached_query("get_all_subordinates", ttl=3600)
    def get_all_subordinates(self, boss_oid: str, max_depth: int = 10) -> List[Dict]:
        """
        Return all subordinates (direct and indirect) of a boss
        """
        query = """
FOR v, e, p IN 1..@max_depth INBOUND
    CONCAT(@collection, '/', @boss_oid)
    GRAPH @graph_name
    RETURN {
        associate_oid: v.associate_oid,
        display_name: v.display_name,
        department: v.department,
        program: v.program,
        level: LENGTH(p.edges)
    }
        """

        cursor = self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'boss_oid': boss_oid,
                'max_depth': max_depth,
                'graph_name': self.graph_name
            }
        )

        return list(cursor)

    @cached_query("get_org_chart", ttl=3600)
    def get_org_chart(self, root_oid: Optional[str] = None) -> Dict:
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
                RETURN emp.associate_oid
            """
            cursor = self.db.aql.execute(
                query_ceo,
                bind_vars={
                    '@collection': self.employees_collection,
                    'graph_name': self.graph_name
                }
            )
            if results := list(cursor):
                root_oid = results[0]
            else:
                return {}
        # Build the tree from the root_oid recursively
        query = """
        FOR v, e, p IN 0..10 INBOUND
            CONCAT(@collection, '/', @root_oid)
            GRAPH @graph_name
            RETURN {
                associate_oid: v.associate_oid,
                display_name: v.display_name,
                department: v.department,
                program: v.program,
                level: LENGTH(p.edges),
                path: p.vertices[*].associate_oid
            }
        """

        cursor = self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'root_oid': root_oid,
                'graph_name': self.graph_name
            }
        )

        return list(cursor)

    @cached_query("get_colleagues", ttl=3600)
    def get_colleagues(self, employee_oid: str) -> List[Dict]:
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
                FILTER colleague.associate_oid != @employee_oid
                RETURN {
                    associate_oid: colleague.associate_oid,
                    display_name: colleague.display_name,
                    department: colleague.department,
                    program: colleague.program
                }
        """

        cursor = self.db.aql.execute(
            query,
            bind_vars={
                'collection': self.employees_collection,
                'employee_oid': employee_oid,
                'graph_name': self.graph_name
            }
        )

        return list(cursor)


# # ============= EJEMPLO DE USO =============

# if __name__ == "__main__":
#     # Inicializar el gestor
#     manager = EmployeeHierarchyManager(
#         arango_host='localhost',
#         arango_port=8529,
#         db_name='company_db',
#         username='root',
#         password='your_password'
#     )

#     # Opción 1: Importar desde PostgreSQL
#     # manager.import_from_postgres(
#     #     "dbname=mydb user=user password=pass host=localhost"
#     # )

#     # Opción 2: Insertar empleados manualmente
#     ceo = Employee('E001', 'Ana García', 'Executive', 'CEO Office', None)
#     cto = Employee('E002', 'Carlos López', 'Technology', 'Engineering', 'E001')
#     dev1 = Employee('E003', 'María Torres', 'Technology', 'Engineering', 'E002')
#     dev2 = Employee('E004', 'Juan Pérez', 'Technology', 'Engineering', 'E002')

#     for emp in [ceo, cto, dev1, dev2]:
#         manager.insert_employee(emp)

#     # ===== EJEMPLOS DE QUERIES =====

#     # 1. ¿María reporta a Ana?
#     print("\n1. ¿María (E003) reporta a Ana (E001)?")
#     print(manager.does_report_to('E003', 'E001'))  # True

#     # 2. ¿Juan reporta a María? (están al mismo nivel)
#     print("\n2. ¿Juan (E004) reporta a María (E003)?")
#     print(manager.does_report_to('E004', 'E003'))  # False

#     # 3. Todos los jefes de María
#     print("\n3. Todos los jefes superiores de María:")
#     superiors = manager.get_all_superiors('E003')
#     for boss in superiors:
#         print(f"  Nivel {boss['level']}: {boss['name']} ({boss['associate_oid']})")

#     # 4. Reportes directos de Carlos
#     print("\n4. Reportes directos de Carlos:")
#     reports = manager.get_direct_reports('E002')
#     for emp in reports:
#         print(f"  - {emp['name']} ({emp['associate_oid']})")

#     # 5. Todos los subordinados de Ana (toda la empresa)
#     print("\n5. Todos los subordinados de Ana (jerarquía completa):")
#     all_subs = manager.get_all_subordinates('E001')
#     for emp in all_subs:
#         print(f"  Nivel {emp['level']}: {emp['name']} ({emp['associate_oid']})")
