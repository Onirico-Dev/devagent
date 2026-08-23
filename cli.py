from core.pipeline import DevAgentPipeline


def main():

    pipeline = DevAgentPipeline(".")

    print("=" * 50)
    print("DevAgent")
    print("Digite 'sair' para encerrar.")
    print("=" * 50)

    while True:

        try:
            command = input("\nDevAgent > ").strip()

        except KeyboardInterrupt:
            print()
            break

        if command.lower() in {
            "sair",
            "exit",
            "quit",
        }:
            break

        if not command:
            continue

        try:
            plan = pipeline.process(command)

            print("\nPlano:")
            print(f"Objetivo: {plan.objective}")

            for change in plan.changes:
                print(
                    f"- {change.change_type.value}: "
                    f"{change.path}"
                )

            if plan.risks:
                print("\nRiscos:")

                for risk in plan.risks:
                    print(f"- {risk}")

        except Exception as error:
            print(f"\nErro: {error}")


if __name__ == "__main__":
    main()
