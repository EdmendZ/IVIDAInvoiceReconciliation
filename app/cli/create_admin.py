import argparse
import getpass

from app.api.auth_dependencies import get_auth_service
from app.domain.admin_users import AdminRole


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an IVIDA reviewer")
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--role",
        choices=[role.value for role in AdminRole],
        default=AdminRole.REVIEWER.value,
    )
    args = parser.parse_args()
    password = getpass.getpass("Password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    user = get_auth_service().create_user(
        username=args.username,
        password=password,
        role=AdminRole(args.role),
    )
    print(f"Created {user.role.value} account: {user.username}")


if __name__ == "__main__":
    main()
