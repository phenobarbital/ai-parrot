<?php
namespace App\Models;
use App\Contracts\Serializable;
/** Represents an application user. */
class User extends Model implements Serializable {
    /** Get the full name. */
    public function getFullName($prefix = '') { return $prefix; }
}
interface Serializable {}
trait HasTimestamps {}
enum Status: string { case Active = 'a'; }
/** Utility helper. */
function helper_function($a, $b) {}
