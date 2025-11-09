import asyncio
import json
from parrot.interfaces.hierarchy import EmployeeHierarchyManager

# ============= EJEMPLO DE USO =============
async def usage_example():
    manager = EmployeeHierarchyManager(
        arango_host='localhost',
        arango_port=8529,
        db_name='navigator',
        username='root',
        password='12345678',
        pg_employees_table='troc.troc_employees'
    )
    async with manager:
        # Import from PostgreSQL:
        # await manager.import_from_postgres()
        # ===== EJEMPLOS DE QUERIES =====
        # 1. ¿Javier le Reporta a Eduardo?
        print("\n1. ¿Javier (G3GAY1DYQWYZQHQ6) reporta a Eduardo (G3D9VQVK98QSBN89)?")
        print(
            await manager.does_report_to('JNXEA935I', '743')
        ) # True
        # 3. Todos los Superiores de Javier León
        print("\n3. Todos los jefes superiores de Javier León:")
        superiors = await manager.get_all_superiors('JNXEA935I')
        for boss in superiors:
            print(f"  Nivel {boss['level']}: {boss['display_name']} ({boss['associate_oid']})")

        # 4. Reportes directos de Jesus
        print("\n4. Reportes directos de Javier:")
        reports = await manager.get_direct_reports('JNXEA935I')
        for emp in reports:
            print(f"  - {emp['display_name']} ({emp['associate_oid']})")

        # 5. Todos los subordinados de Eduardo (toda la empresa)
        print("\n5. Todos los subordinados de Eduardo (jerarquía completa):")
        all_subs = await manager.get_all_subordinates('743', max_depth=1)
        for emp in all_subs:
            print(f"  Nivel {emp['level']}: {emp['display_name']} ({emp['associate_oid']})")

        # 6. Organigrama completo
        print("\n6. Organigrama completo de la empresa:")
        org_chart = await manager.get_org_chart(root_oid='743')
        print(json.dumps(org_chart, indent=2))

        # 7. Compañeros de Javier
        print("\n7. Compañeros de Javier:")
        colleagues = await manager.get_colleagues('JNXEA935I')
        for emp in colleagues:
            print(f"  - {emp['display_name']} ({emp['associate_oid']})")

        # 8. ¿Son compañeros Javier y Jesus?
        are_colleagues = await manager.are_colleagues('JNXEA935I', 'BP7TMUC7Q')
        print(
            f"¿Son compañeros Javier y Jesus?: {are_colleagues}"
        )

        # 9 . ¿Quién es el jefe común más cercano entre Javier y Jesus?
        common_boss = await manager.get_closest_common_boss('JNXEA935I', 'BP7TMUC7Q')
        print(
            f"\n9. ¿Quién es el jefe común más cercano entre Javier y Jesus?: "
            f"{common_boss['display_name']} ({common_boss['associate_oid']})"
        )

        # 10. Es Brett el jefe directo de Jesus?
        is_brett_boss = await manager.is_boss_of('BP7TMUC7Q', '889', direct_only=False)
        print(
            f"\n10. ¿Es Brett el jefe directo de Jesus?: {is_brett_boss['is_manager']}"
        )

if __name__ == "__main__":
    asyncio.run(usage_example())
