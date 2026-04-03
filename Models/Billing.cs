using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Patient_Management_System.Models
{
    public class Billing
    {
        [Key]
        [DatabaseGenerated(DatabaseGeneratedOption.Identity)]
        public int Id { get; set; }
        [Required(ErrorMessage = "PatientId is required!!!")]
        public int PatientId { get; set; } = 0;
        public string AccountId { get; set; } = string.Empty;
        public string Status { get; set; } = "INACTIVE";
    }
}