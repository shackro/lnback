import typer

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import SessionLocal, engine
from app.models import AdminUser, Base

cli = typer.Typer()


def create_admin(email: str, password: str) -> None:
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 254:
        raise typer.BadParameter("Enter a valid email address.", param_hint="--email")
    if len(password) < 12 or len(password) > 256:
        raise typer.BadParameter("Password must be between 12 and 256 characters.")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(AdminUser).filter(AdminUser.email == email).first() is not None:
            raise typer.BadParameter("An admin with that email already exists.", param_hint="--email")
        db.add(AdminUser(email=email, hashed_password=get_password_hash(password), role="admin"))
        db.commit()
    typer.echo(f"Admin account created for {email}.")


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
