import asyncio
from parrot.interfaces.hierarchy import EmployeeHierarchyManager, Employee

# ============= EJEMPLO DE USO =============

if __name__ == "__main__":
    # Inicializar el gestor
    manager = EmployeeHierarchyManager(
        arango_host='localhost',
        arango_port=8529,
        db_name='navigator',
        username='root',
        password='12345678',
        pg_employees_table='troc.troc_employees'
    )

    # Importar desde PostgreSQL
    # asyncio.run(manager.import_from_postgres())

    # ===== EJEMPLOS DE QUERIES =====

    # 1. ¿Javier le Reporta a Eduardo?
    print("\n1. ¿Javier (G3GAY1DYQWYZQHQ6) reporta a Eduardo (G3D9VQVK98QSBN89)?")
    print(
        asyncio.run(
            manager.does_report_to('G3GAY1DYQWYZQHQ6', 'G3D9VQVK98QSBN89')
        )
    ) # True

    # # 2. ¿Juan reporta a María? (están al mismo nivel)
    # print("\n2. ¿Juan (E004) reporta a María (E003)?")
    # print(manager.does_report_to('E004', 'E003'))  # False

    # 3. Todos los Superiores de Javier León
    print("\n3. Todos los jefes superiores de Javier León:")
    superiors = asyncio.run(manager.get_all_superiors('G3GAY1DYQWYZQHQ6'))
    for boss in superiors:
        print(f"  Nivel {boss['level']}: {boss['name']} ({boss['associate_oid']})")

    # # 4. Reportes directos de Carlos
    # print("\n4. Reportes directos de Carlos:")
    # reports = manager.get_direct_reports('E002')
    # for emp in reports:
    #     print(f"  - {emp['name']} ({emp['associate_oid']})")

    # # 5. Todos los subordinados de Ana (toda la empresa)
    # print("\n5. Todos los subordinados de Ana (jerarquía completa):")
    # all_subs = manager.get_all_subordinates('E001')
    # for emp in all_subs:
    #     print(f"  Nivel {emp['level']}: {emp['name']} ({emp['associate_oid']})")
