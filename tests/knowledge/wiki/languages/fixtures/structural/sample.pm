package MyApp::Model::User;

use strict;
use warnings;
use Moose;
use MyApp::Schema;

has 'name' => (is => 'ro');

=head2 validate

Validate the user.

=cut

sub validate {
    my ($self) = @_;
    return 1;
}

package MyApp::Other;

field $x;

require Baz;

sub bar {
}

1;
