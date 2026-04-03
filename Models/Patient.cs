using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Patient_Management_System.Models
{
    public class Patient
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int Id { get; set; }

        [Required(ErrorMessage = "Patient Name is required!!!")]
        [StringLength(100, ErrorMessage = "Patient Name cannot be longer than 100 characters!!!")]
        public string Name { get; set; } = string.Empty;

        [Required(ErrorMessage = "Patient Email is required!!!")]
        [EmailAddress(ErrorMessage = "Invalid Email Address!!!")]
        public string Email { get; set; } = string.Empty;

        [Required(ErrorMessage = "Patient Address is required!!!")]
        [StringLength(200, ErrorMessage = "Patient Address cannot be longer than 200 characters!!!")]
        public string Address { get; set; } = string.Empty;

        [DataType(DataType.Date, ErrorMessage = "Invalid Date of Birth!!!")]
        public DateOnly DateOfBirth { get; set; }

        [DataType(DataType.Date, ErrorMessage = "Invalid Registered Date!!!")]
        public DateOnly RegisteredDate { get; set; } 
    }
}