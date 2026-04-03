using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Patient_Management_System.Models
{
    public class User
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int Id { get; set; }

        [Required(ErrorMessage = "User Email is required!!!")]
        [EmailAddress(ErrorMessage = "Invalid Email Address!!!")]
        public string Email { get; set; } = string.Empty;

        [Required(ErrorMessage = "Password is required!!!")]
        public string Password { get; set; } = string.Empty;

        public UserRole Role { get; set; }
    }

    public enum UserRole
    {
        ADMIN,
        USER
    }
}