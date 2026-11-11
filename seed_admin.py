import typer

from app.core.config import settings
from app.core.dependencies import ADMIN_PERMISSIONS
from app.core.security import get_password_hash
from app.db.session import SessionLocal, engine, ensure_admin_security_columns
from app.models import AdminUser, Base
from app.services.admin_access import record_admin_event

cli = typer.Typer()


def create_admin(email: str, password: str) -> None:
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise typer.BadParameter("Enter a valid email address.", param_hint="--email")
    if len(password) < 12 or len(password) > 256:
        raise typer.BadParameter("Password must be between 12 and 256 characters.")

    Base.metadata.create_all(bind=engine)
    ensure_admin_security_columns(engine)
    with SessionLocal() as db:
        if db.query(AdminUser).first() is not None:
            raise typer.BadParameter(
                "Initial super administrator already exists. Create additional admins from the admin control room.",
                param_hint="--email",
            )
        admin = AdminUser(
            email=email,
            hashed_password=get_password_hash(password),
            role="super_admin",
            permissions=sorted(ADMIN_PERMISSIONS),
        )
        db.add(admin)
        record_admin_event(
            db,
            actor_email="system.bootstrap",
            action="genesis_super_admin_created",
            target_admin_email=email,
            details={"permissions": admin.permissions},
        )
        db.commit()
    typer.echo(f"Initial super administrator created for {email}.")


def require_secret_key() -> None:
    if len(settings.secret_key.encode("utf-8")) < 32:
        typer.echo("Set SECRET_KEY to a random value of at least 32 bytes in backend/.env first.", err=True)
        raise typer.Exit(code=1)


@cli.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        require_secret_key()
        email = typer.prompt("Admin email")
        password = typer.prompt("Admin password", hide_input=True, confirmation_prompt=True)
        create_admin(email, password)


@cli.command()
def createsuperuser(email: str = typer.Option(..., prompt="Admin email")) -> None:
    require_secret_key()
    password = typer.prompt("Admin password", hide_input=True, confirmation_prompt=True)
    create_admin(email, password)


if __name__ == "__main__":
    cli()
