"""Remove obsolete Candidate.code field and related DB constraints.

This migration was added to remove the database column left over after
the model's `code` attribute was removed. It drops the index and unique
constraint that referenced `code`, then removes the field itself.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("voting", "0002_alter_ballot_candidate_ballotchoice"),
    ]

    operations = [
        # Remove the index on (election, code)
        migrations.RemoveIndex(
            model_name="candidate",
            name="idx_candidate_election_code",
        ),

        # Remove unique_together constraint that referenced `code`
        migrations.AlterUniqueTogether(
            name="candidate",
            unique_together=set(),
        ),

        # Finally drop the actual column
        migrations.RemoveField(
            model_name="candidate",
            name="code",
        ),
    ]
